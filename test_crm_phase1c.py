import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase1C(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'test_rino', 'crm_agent_all', 'crm_agent_regular', 'crm_agent_other')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20001, 'test_rino', 'test_rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_agent_all', 'agent_all@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_all_leads": true}'),
            (20003, 'crm_agent_regular', 'agent_reg@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true}'),
            (20004, 'crm_agent_other', 'agent_oth@test.com', 'pwd', TRUE, '{"crm_view": true}')
        """, commit=True)

        # Clean leads and campaigns
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)

    def tearDown(self):
        # Cleanup
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20001, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def test_1_create_standalone_prospect(self):
        """TEST 1: Create standalone prospect."""
        self.login_as('crm_agent_regular', 20003)
        response = self.client.post('/crm/leads', json={
            "name": "Test Prospect",
            "phone": "999888777",
            "email": "prospect@test.com",
            "source": "FACEBOOK",
            "notes": "Some notes"
        })
        self.assertEqual(response.status_code, 201)
        data = response.get_json()
        self.assertIn('id', data)

        # Verify in DB
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (data['id'],), one=True)
        self.assertIsNotNone(lead)
        self.assertEqual(lead['name'], "Test Prospect")
        self.assertEqual(lead['stage'], "NEW")
        self.assertIsNone(lead['member_id'])

    def test_2_create_existing_member_lead(self):
        """TEST 2: Create existing-member lead and snapshot values."""
        # Insert a temp member
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (30001, 'Test Member One', '555444333', 'member_one@test.com', 'Active')
        """, commit=True)

        self.login_as('crm_agent_regular', 20003)
        # Client tries to send conflict data, but member values should override
        response = self.client.post('/crm/leads', json={
            "member_id": 30001,
            "name": "Fake Name",
            "phone": "000",
            "source": "INSTAGRAM"
        })
        self.assertEqual(response.status_code, 201)
        data = response.get_json()

        # Verify snapshot in DB
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (data['id'],), one=True)
        self.assertEqual(lead['name'], "Test Member One")
        self.assertEqual(lead['phone'], "555444333")
        self.assertEqual(lead['email'], "member_one@test.com")
        self.assertEqual(lead['member_id'], 30001)

    def test_3_reject_nonexistent_member_id(self):
        """TEST 3: Reject nonexistent member_id."""
        self.login_as('crm_agent_regular', 20003)
        response = self.client.post('/crm/leads', json={
            "member_id": 999999,
            "source": "WALK_IN"
        })
        self.assertEqual(response.status_code, 400)

    def test_4_reject_second_active_lead_for_member(self):
        """TEST 4: Reject second active Lead for same Member."""
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (30002, 'Test Member Two', '555444222', 'member_two@test.com', 'Active')
        """, commit=True)

        self.login_as('crm_agent_regular', 20003)
        # Insert first active lead
        r1 = self.client.post('/crm/leads', json={"member_id": 30002, "source": "WALK_IN"})
        self.assertEqual(r1.status_code, 201)

        # Insert second active lead
        r2 = self.client.post('/crm/leads', json={"member_id": 30002, "source": "FACEBOOK"})
        self.assertEqual(r2.status_code, 409)
        self.assertEqual(r2.get_json()['error'], "active_lead_exists")

    def test_5_allow_new_lead_after_terminal(self):
        """TEST 5: Allow new lead for same Member after previous Lead becomes terminal."""
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (30003, 'Test Member Three', '555444111', 'member_three@test.com', 'Active')
        """, commit=True)

        self.login_as('crm_agent_regular', 20003)
        r1 = self.client.post('/crm/leads', json={"member_id": 30003, "source": "WALK_IN"})
        lead_id = r1.get_json()['id']

        # Set first lead to WON (terminal)
        query_db("UPDATE crm_leads SET stage = 'WON' WHERE id = %s", (lead_id,), commit=True)

        # Insert second lead
        r2 = self.client.post('/crm/leads', json={"member_id": 30003, "source": "FACEBOOK"})
        self.assertEqual(r2.status_code, 201)

    def test_6_reject_active_non_member_duplicate_phone(self):
        """TEST 6: Reject active non-member duplicate phone."""
        self.login_as('crm_agent_regular', 20003)
        r1 = self.client.post('/crm/leads', json={"name": "Prospect A", "phone": "111222333", "source": "WALK_IN"})
        self.assertEqual(r1.status_code, 201)

        r2 = self.client.post('/crm/leads', json={"name": "Prospect B", "phone": "111222333", "source": "INSTAGRAM"})
        self.assertEqual(r2.status_code, 409)

    def test_7_detect_existing_member_match(self):
        """TEST 7: Detect existing Member match when phone matches existing Member."""
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (30004, 'Test Member Four', '777666555', 'member_four@test.com', 'Active')
        """, commit=True)

        self.login_as('crm_agent_regular', 20003)
        response = self.client.post('/crm/leads', json={
            "name": "Prospect Fake",
            "phone": "777666555",
            "source": "WALK_IN"
        })
        self.assertEqual(response.status_code, 409)
        data = response.get_json()
        self.assertEqual(data['error'], "member_match_found")
        self.assertEqual(data['details']['members'][0]['id'], 30004)

    def test_8_list_pagination(self):
        """TEST 8: List pagination works."""
        self.login_as('crm_agent_all', 20002)
        # Create 5 leads
        for i in range(5):
            self.client.post('/crm/leads', json={"name": f"Prospect {i}", "phone": f"100{i}", "source": "WALK_IN"})

        response = self.client.get('/crm/leads?page=1&per_page=2')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['total'], 5)
        self.assertEqual(data['pages'], 3)

    def test_9_stage_filter(self):
        """TEST 9: Stage filter works."""
        self.login_as('crm_agent_all', 20002)
        r1 = self.client.post('/crm/leads', json={"name": "Prospect A", "phone": "101", "source": "WALK_IN"})
        r2 = self.client.post('/crm/leads', json={"name": "Prospect B", "phone": "102", "source": "WALK_IN"})

        lead_id = r1.get_json()['id']
        query_db("UPDATE crm_leads SET stage = 'FOLLOW_UP' WHERE id = %s", (lead_id,), commit=True)

        response = self.client.get('/crm/leads?stage=FOLLOW_UP')
        data = response.get_json()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['id'], lead_id)

    def test_10_member_status_filter(self):
        """TEST 10: Member/prospect filter works."""
        query_db("INSERT INTO members (id, name, phone, email, membership_status) VALUES (30005, 'Test Member Five', '103', 'm5@test.com', 'Active')", commit=True)
        self.login_as('crm_agent_all', 20002)

        self.client.post('/crm/leads', json={"name": "Prospect A", "phone": "104", "source": "WALK_IN"})
        self.client.post('/crm/leads', json={"member_id": 30005, "source": "WALK_IN"})

        # Query prospects only
        resp_p = self.client.get('/crm/leads?member_status=prospect')
        self.assertEqual(len(resp_p.get_json()['items']), 1)
        self.assertIsNone(resp_p.get_json()['items'][0]['member_id'])

        # Query members only
        resp_m = self.client.get('/crm/leads?member_status=member')
        self.assertEqual(len(resp_m.get_json()['items']), 1)
        self.assertEqual(resp_m.get_json()['items'][0]['member_id'], 30005)

    def test_11_search(self):
        """TEST 11: Search works."""
        self.login_as('crm_agent_all', 20002)
        self.client.post('/crm/leads', json={"name": "Unique Search Name", "phone": "105", "source": "WALK_IN"})
        self.client.post('/crm/leads', json={"name": "Standard Name", "phone": "106", "source": "WALK_IN"})

        response = self.client.get('/crm/leads?search=Unique')
        data = response.get_json()
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['name'], "Unique Search Name")

    def test_12_rino_view_all(self):
        """TEST 12: Rino can view all Leads."""
        # Create lead by regular agent
        self.login_as('crm_agent_regular', 20003)
        self.client.post('/crm/leads', json={"name": "Regular Lead", "phone": "107", "source": "WALK_IN"})

        # Retrieve using Rino session
        # Rino user in test session check
        self.login_as('rino', 2)
        response = self.client.get('/crm/leads')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 1)

    def test_13_crm_all_leads_view_all(self):
        """TEST 13: crm_all_leads user can view all Leads."""
        self.login_as('crm_agent_regular', 20003)
        self.client.post('/crm/leads', json={"name": "Regular Lead", "phone": "108", "source": "WALK_IN"})

        self.login_as('crm_agent_all', 20002)
        response = self.client.get('/crm/leads')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()['total'], 1)

    def test_14_regular_user_assigned_lead(self):
        """TEST 14: Regular user can see assigned Lead."""
        # Create lead by admin
        self.login_as('crm_agent_all', 20002)
        r = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "109", "source": "WALK_IN"})
        lead_id = r.get_json()['id']
        # Manually set assigned_user_id
        query_db("UPDATE crm_leads SET assigned_user_id = 20003 WHERE id = %s", (lead_id,), commit=True)

        self.login_as('crm_agent_regular', 20003)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 200)

    def test_15_regular_user_own_unassigned_lead(self):
        """TEST 15: Regular user can see own unassigned Lead."""
        self.login_as('crm_agent_regular', 20003)
        r = self.client.post('/crm/leads', json={"name": "Own Lead", "phone": "110", "source": "WALK_IN"})
        lead_id = r.get_json()['id']

        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 200)

    def test_16_regular_user_cannot_view_other_assigned_lead(self):
        """TEST 16: Regular user cannot view Lead assigned to another user."""
        self.login_as('crm_agent_all', 20002)
        r = self.client.post('/crm/leads', json={"name": "Other Assigned", "phone": "111", "source": "WALK_IN"})
        lead_id = r.get_json()['id']
        query_db("UPDATE crm_leads SET assigned_user_id = 20004 WHERE id = %s", (lead_id,), commit=True)

        # Try regular agent
        self.login_as('crm_agent_regular', 20003)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 403)

    def test_17_update_permitted_fields(self):
        """TEST 17: Update permitted Lead fields including existing member snapshots independently."""
        # 1. Create temporary member
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (30008, 'Test Member Snap', '112233', 'snap@test.com', 'Active')
        """, commit=True)

        self.login_as('crm_agent_regular', 20003)
        # 2. Create lead linked to member
        r = self.client.post('/crm/leads', json={"member_id": 30008, "source": "WALK_IN"})
        lead_id = r.get_json()['id']

        # 3. Edit CRM lead snapshot name, phone, email
        response = self.client.patch(f'/crm/leads/{lead_id}', json={
            "name": "Independently Edited Name",
            "phone": "9999",
            "email": "snap_edited@test.com",
            "notes": "Updated notes"
        })
        self.assertEqual(response.status_code, 200)

        # 4. Verify snapshot is updated in crm_leads
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['name'], "Independently Edited Name")
        self.assertEqual(lead['phone'], "9999")
        self.assertEqual(lead['email'], "snap_edited@test.com")

        # 5. Verify members table remains completely unchanged
        member = query_db("SELECT * FROM members WHERE id = 30008", one=True)
        self.assertEqual(member['name'], "Test Member Snap")
        self.assertEqual(member['phone'], "112233")
        self.assertEqual(member['email'], "snap@test.com")

    def test_18_patch_protected_fields_fail(self):
        """TEST 18: PATCH with protected fields fails with HTTP 400."""
        self.login_as('crm_agent_regular', 20003)
        r = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "113", "source": "WALK_IN"})
        lead_id = r.get_json()['id']

        # Try to patch protected fields
        response = self.client.patch(f'/crm/leads/{lead_id}', json={
            "member_id": 99,
            "stage": "WON",
            "assigned_user_id": 20004
        })
        self.assertEqual(response.status_code, 400)
        data = response.get_json()
        self.assertEqual(data['error'], "protected_field")
        self.assertIn("member_id", data['fields'])
        self.assertIn("stage", data['fields'])
        self.assertIn("assigned_user_id", data['fields'])

        # Verify database remains unchanged
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead['member_id'])
        self.assertEqual(lead['stage'], "NEW")
        self.assertIsNone(lead['assigned_user_id'])

    def test_19_archive_lead_hides_it(self):
        """TEST 19: Archive Lead hides it from default list."""
        self.login_as('crm_agent_regular', 20003)
        r = self.client.post('/crm/leads', json={"name": "To Archive", "phone": "114", "source": "WALK_IN"})
        lead_id = r.get_json()['id']

        # Archive
        arch = self.client.post(f'/crm/leads/{lead_id}/archive')
        self.assertEqual(arch.status_code, 200)

        # List
        resp_list = self.client.get('/crm/leads')
        self.assertEqual(resp_list.get_json()['total'], 0)

    def test_20_archived_row_exists_in_db(self):
        """TEST 20: Archived Lead row still exists in DB."""
        self.login_as('crm_agent_regular', 20003)
        r = self.client.post('/crm/leads', json={"name": "To Archive", "phone": "115", "source": "WALK_IN"})
        lead_id = r.get_json()['id']
        self.client.post(f'/crm/leads/{lead_id}/archive')

        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNotNone(lead)
        self.assertTrue(lead['is_archived'])

    def test_21_member_search_endpoint(self):
        """TEST 21: Member search endpoint returns bounded results."""
        query_db("INSERT INTO members (id, name, phone, email, membership_status) VALUES (30006, 'Test Search One', '116', 's1@test.com', 'Active')", commit=True)
        query_db("INSERT INTO members (id, name, phone, email, membership_status) VALUES (30007, 'Test Search Two', '117', 's2@test.com', 'Active')", commit=True)

        self.login_as('crm_agent_regular', 20003)
        response = self.client.get('/crm/members/search?q=Search')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data), 2)

    def test_22_unauthorized_user_cannot_enumerate_detail(self):
        """TEST 22: Unauthorized user cannot view lead detail by ID."""
        self.login_as('crm_agent_all', 20002)
        r = self.client.post('/crm/leads', json={"name": "Private Lead", "phone": "118", "source": "WALK_IN"})
        lead_id = r.get_json()['id']
        # Assign to other user
        query_db("UPDATE crm_leads SET assigned_user_id = 20004 WHERE id = %s", (lead_id,), commit=True)

        # Access with regular user
        self.login_as('crm_agent_regular', 20003)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 403)

if __name__ == '__main__':
    unittest.main()
