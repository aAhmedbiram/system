import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase1D(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_assign_user', 'crm_agent_a', 'crm_agent_b', 'unapproved_user')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (20001, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_assign_user', 'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true}'),
            (20003, 'crm_agent_a', 'agent_a@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (20004, 'crm_agent_b', 'agent_b@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (20005, 'unapproved_user', 'unapproved@test.com', 'pwd', FALSE, '{"crm_view": true}')
        """, commit=True)

        # Clean leads and activities
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)
        query_db("DELETE FROM users WHERE id IN (20001, 20002, 20003, 20004, 20005)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def test_a_user_listing(self):
        """TEST A: User listing."""
        # 1. Rino can list
        self.login_as('rino', 20001)
        response = self.client.get('/crm/users')
        self.assertEqual(response.status_code, 200)
        users = response.get_json()
        # Verify unapproved user is not in the list
        self.assertFalse(any(u['username'] == 'unapproved_user' for u in users))
        # Verify sensitive fields like password are not returned
        self.assertFalse('password' in users[0])

        # 2. crm_assign user can list
        self.login_as('crm_assign_user', 20002)
        response = self.client.get('/crm/users')
        self.assertEqual(response.status_code, 200)

        # 3. Regular agent without crm_assign receives 302 redirect
        self.login_as('crm_agent_a', 20003)
        response = self.client.get('/crm/users')
        self.assertEqual(response.status_code, 302)

    def test_b_single_assignment(self):
        """TEST B: Single assignment."""
        self.login_as('crm_assign_user', 20002)

        # Create lead
        res = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "1001", "source": "WALK_IN"})
        self.assertEqual(res.status_code, 201)
        lead_id = res.get_json()['id']

        # Assign lead to Agent A
        response = self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})
        self.assertEqual(response.status_code, 200)

        # Verify lead state in DB
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['assigned_user_id'], 20003)
        self.assertEqual(lead['assigned_by_user_id'], 20002)
        self.assertIsNotNone(lead['assigned_at'])
        self.assertEqual(lead['created_by_user_id'], 20002)

        # Verify assignment activity logged
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s", (lead_id,), one=True)
        self.assertIsNotNone(act)
        self.assertEqual(act['activity_type'], 'ASSIGNED')
        self.assertEqual(act['new_assigned_user_id'], 20003)

    def test_c_reassignment(self):
        """TEST C: Reassignment."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "1002", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Assign to Agent A
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})
        # Reassign to Agent B
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20004})

        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['assigned_user_id'], 20004)

        # Verify activity transition
        acts = query_db("SELECT * FROM crm_activities WHERE lead_id = %s ORDER BY id ASC", (lead_id,))
        self.assertEqual(len(acts), 2)
        self.assertEqual(acts[0]['new_assigned_user_id'], 20003)
        self.assertEqual(acts[1]['old_assigned_user_id'], 20003)
        self.assertEqual(acts[1]['new_assigned_user_id'], 20004)

    def test_d_unassignment(self):
        """TEST D: Unassignment."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "1003", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})
        response = self.client.post(f'/crm/leads/{lead_id}/unassign')
        self.assertEqual(response.status_code, 200)

        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead['assigned_user_id'])
        self.assertEqual(lead['assigned_by_user_id'], 20002)

        # Verify unassign activity logged
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s ORDER BY id DESC LIMIT 1", (lead_id,), one=True)
        self.assertEqual(act['old_assigned_user_id'], 20003)
        self.assertIsNone(act['new_assigned_user_id'])

    def test_e_target_validation(self):
        """TEST E: Target validation."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "1004", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # 1. Nonexistent user
        r1 = self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 999999})
        self.assertEqual(r1.status_code, 404)

        # 2. Unapproved user
        r2 = self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20005})
        self.assertEqual(r2.status_code, 409)

    def test_f_lead_validation(self):
        """TEST F: Lead validation."""
        self.login_as('crm_assign_user', 20002)
        # 1. Nonexistent lead
        r1 = self.client.post('/crm/leads/999999/assign', json={"user_id": 20003})
        self.assertEqual(r1.status_code, 404)

        # 2. Archived lead cannot be assigned
        res = self.client.post('/crm/leads', json={"name": "Prospect", "phone": "1005", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        query_db("UPDATE crm_leads SET is_archived = TRUE WHERE id = %s", (lead_id,), commit=True)
        r2 = self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})
        self.assertEqual(r2.status_code, 409)

    def test_g_bulk_assignment(self):
        """TEST G: Bulk assignment transactions."""
        self.login_as('crm_assign_user', 20002)

        # Create 3 leads
        r1 = self.client.post('/crm/leads', json={"name": "P1", "phone": "1006", "source": "WALK_IN"})
        r2 = self.client.post('/crm/leads', json={"name": "P2", "phone": "1007", "source": "WALK_IN"})
        r3 = self.client.post('/crm/leads', json={"name": "P3", "phone": "1008", "source": "WALK_IN"})

        ids = [r1.get_json()['id'], r2.get_json()['id'], r3.get_json()['id']]

        # 1. Successful bulk assignment
        response = self.client.post('/crm/leads/bulk-assign', json={"lead_ids": ids, "user_id": 20003})
        self.assertEqual(response.status_code, 200)

        # Verify all assigned
        for lid in ids:
            lead = query_db("SELECT assigned_user_id FROM crm_leads WHERE id = %s", (lid,), one=True)
            self.assertEqual(lead['assigned_user_id'], 20003)

        # 2. Bulk assignment fails and rolls back on invalid lead ID
        # Unassign first
        query_db("UPDATE crm_leads SET assigned_user_id = NULL", commit=True)

        response = self.client.post('/crm/leads/bulk-assign', json={"lead_ids": ids + [999999], "user_id": 20004})
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()['error'], "bulk_assignment_failed")
        self.assertIn(999999, response.get_json()['details']['invalid_lead_ids'])

        # Verify rollback - no leads updated to 20004
        for lid in ids:
            lead = query_db("SELECT assigned_user_id FROM crm_leads WHERE id = %s", (lid,), one=True)
            self.assertIsNone(lead['assigned_user_id'])

    def test_h_visibility_after_assignment(self):
        """TEST H: Visibility transitions."""
        # Creator = Agent A (20003), creates lead
        self.login_as('crm_agent_a', 20003)
        res = self.client.post('/crm/leads', json={"name": "Private Lead", "phone": "1009", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Creator can view unassigned lead
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 200)

        # Admin assigns lead to Agent B (20004)
        self.login_as('crm_assign_user', 20002)
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20004})

        # Creator (Agent A) now loses access
        self.login_as('crm_agent_a', 20003)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 403)

        # Assignee (Agent B) can see it
        self.login_as('crm_agent_b', 20004)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 200)

        # Admin unassigns lead
        self.login_as('crm_assign_user', 20002)
        self.client.post(f'/crm/leads/{lead_id}/unassign')

        # Creator (Agent A) can see it again since it is unassigned
        self.login_as('crm_agent_a', 20003)
        response = self.client.get(f'/crm/leads/{lead_id}')
        self.assertEqual(response.status_code, 200)

    def test_i_single_assignment_rollback(self):
        """TEST I: Prove that a database error on activity insert rolls back single assignment."""
        self.login_as('crm_assign_user', 20002)

        # Create lead
        res = self.client.post('/crm/leads', json={"name": "Rollback Assign", "phone": "1010", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Mock get_current_user to return a username that is too long for VARCHAR(255)
        from unittest.mock import patch
        with patch('system_app.crm.routes.get_current_user') as mock_get_user:
            mock_get_user.return_value = {
                "id": 20002,
                "username": "x" * 300,  # Violates crm_activities.user_username_snapshot VARCHAR(255)
                "permissions": {"crm_assign": True}
            }

            # Post assignment - should fail due to database check/truncation constraint
            response = self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})
            self.assertEqual(response.status_code, 500)

        # Verify database state was rolled back - lead must NOT be assigned to 20003
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead['assigned_user_id'])
        self.assertIsNone(lead['assigned_by_user_id'])

    def test_j_single_unassignment_rollback(self):
        """TEST J: Prove that a database error on activity insert rolls back single unassignment."""
        self.login_as('crm_assign_user', 20002)

        # Create lead and assign it normally first
        res = self.client.post('/crm/leads', json={"name": "Rollback Unassign", "phone": "1011", "source": "WALK_IN"})
        lead_id = res.get_json()['id']
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # Mock get_current_user with too long username
        from unittest.mock import patch
        with patch('system_app.crm.routes.get_current_user') as mock_get_user:
            mock_get_user.return_value = {
                "id": 20002,
                "username": "x" * 300,
                "permissions": {"crm_assign": True}
            }

            # Post unassignment - should fail due to database check/truncation constraint
            response = self.client.post(f'/crm/leads/{lead_id}/unassign')
            self.assertEqual(response.status_code, 500)

        # Verify database state was rolled back - lead must still be assigned to 20003
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['assigned_user_id'], 20003)

if __name__ == '__main__':
    unittest.main()
