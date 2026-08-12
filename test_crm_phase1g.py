import unittest
import datetime
import threading
import time
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase1G(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_converter', 'crm_agent_a', 'crm_agent_b')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_converter', 'converter@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_assign": true, "crm_convert": true, "crm_all_leads": true, "crm_update_stage": true}'),
            (20003, 'crm_agent_a', 'agent_a@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_convert": true}'),
            (20004, 'crm_agent_b', 'agent_b@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_all_leads": true}')
        """, commit=True)

        # Clean crm and member logs
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs", commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%' OR phone IN ('1111', '2222', '3333', '4444', '5555', '6666')", commit=True)

    def tearDown(self):
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs", commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%' OR phone IN ('1111', '2222', '3333', '4444', '5555', '6666')", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    # ==========================================
    # A. PROSPECT CONVERSION
    # ==========================================

    def test_1_convert_prospect_success(self):
        """TEST 1: Converts a prospect lead to a member successfully."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Prospect", "phone": "1111", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Convert
        payload = {
            "membership_packages": "3 Months",
            "starting_date": "2026-08-15"
        }
        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json=payload)
        self.assertEqual(res_conv.status_code, 200)
        data = res_conv.get_json()

        self.assertEqual(data['status'], 'converted')
        self.assertEqual(data['conversion_type'], 'new_member')
        self.assertEqual(data['stage'], 'WON')

        # Verify Lead in DB
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['stage'], 'WON')
        self.assertIsNotNone(lead['member_id'])
        self.assertIsNotNone(lead['converted_at'])
        self.assertEqual(lead['converted_by_user_id'], 20002)

        # Verify Activity Log
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s", (lead_id,), one=True)
        self.assertEqual(act['activity_type'], 'CONVERTED')
        self.assertEqual(act['result'], 'NEW_MEMBER')

    # ==========================================
    # B. EXISTING MEMBER REACTIVATION
    # ==========================================

    def test_2_reactivate_existing_member_success(self):
        """TEST 2: Reactivates an existing member lead successfully."""
        self.login_as('crm_converter', 20002)

        # Create member manually first
        member_id = query_db(
            "INSERT INTO members (name, phone, membership_packages, starting_date) "
            "VALUES ('Test Existing Member', '2222', '1 Month', '2026-08-15') RETURNING id;", one=True, commit=True
        )['id']

        # Insert linked lead directly to bypass member match duplicate check on lead creation
        lead_id = query_db(
            "INSERT INTO crm_leads (name, phone, source, member_id, stage) "
            "VALUES ('Test Existing Member', '2222', 'WALK_IN', %s, 'NEW') RETURNING id;",
            (member_id,), one=True, commit=True
        )['id']

        # Convert / Reactivate
        payload = {
            "membership_packages": "3 Months",
            "starting_date": "2026-09-15"
        }
        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json=payload)
        self.assertEqual(res_conv.status_code, 200)
        data = res_conv.get_json()

        self.assertEqual(data['conversion_type'], 'reactivation')

        # Verify renewal log and invoice
        rlog = query_db("SELECT * FROM renewal_logs WHERE member_id = %s", (member_id,), one=True)
        self.assertIsNotNone(rlog)

        # Verify Activity Log
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s", (lead_id,), one=True)
        self.assertEqual(act['activity_type'], 'REACTIVATED')
        self.assertEqual(act['result'], 'REACTIVATION')

    # ==========================================
    # C. VALIDATION & STATE GUARDS
    # ==========================================

    def test_3_convert_lost_lead_rejected(self):
        """TEST 3: Rejects conversion attempts from LOST leads."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Lost", "phone": "3333", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Set to lost
        self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "LOST", "lost_reason": "PRICE"})

        # Attempt conversion
        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
        self.assertEqual(res_conv.status_code, 409)

    def test_4_convert_archived_lead_rejected(self):
        """TEST 4: Rejects conversion attempts from archived leads."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Archived", "phone": "4444", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Archive
        self.client.post(f'/crm/leads/{lead_id}/archive')

        # Attempt conversion
        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
        self.assertEqual(res_conv.status_code, 409)

    def test_5_convert_already_won_rejected(self):
        """TEST 5: Rejects conversion attempts on already WON leads."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Double", "phone": "5555", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Convert first time
        self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})

        # Convert second time
        res_conv2 = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
        self.assertEqual(res_conv2.status_code, 409)
        self.assertEqual(res_conv2.get_json()['error'], 'already_converted')

    # ==========================================
    # D. PERMISSIONS & VISIBILITY
    # ==========================================

    def test_6_to_10_permission_rules(self):
        """TEST 6-10: Asserts permission requirements and visibility restrictions."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Permissions", "phone": "6666", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # 1. Assign to manager (User 20002)
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20002})

        # 2. Agent A has crm_convert but cannot view manager's lead - denied (403)
        self.login_as('crm_agent_a', 20003)
        r_a = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
        self.assertEqual(r_a.status_code, 403)

        # 3. Agent B has crm_all_leads but lacks crm_convert - denied (302 redirect)
        self.login_as('crm_agent_b', 20004)
        r_b = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
        self.assertEqual(r_b.status_code, 302)

    # ==========================================
    # E. CONCURRENCY TESTS
    # ==========================================

    def test_11_concurrent_conversion_requests(self):
        """TEST 11: Two simultaneous conversion requests result in exactly one successful member."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Concurrent", "phone": "12345", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        status_codes = []

        def run_conv():
            # Setup context manually inside thread
            with app.test_request_context():
                with self.client.session_transaction() as sess:
                    sess['user_id'] = 20002
                    sess['username'] = 'crm_converter'
                r = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
                status_codes.append(r.status_code)

        t1 = threading.Thread(target=run_conv)
        t2 = threading.Thread(target=run_conv)
        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertIn(200, status_codes)
        self.assertIn(409, status_codes) # One gets duplicate/already converted conflict

        # Verify exactly one member created
        members = query_db("SELECT * FROM members WHERE phone = '12345'")
        self.assertEqual(len(members), 1)

    # ==========================================
    # F. ROLLBACK TESTS
    # ==========================================

    def test_12_rollback_on_crm_update_fail(self):
        """TEST 12: Forces fail on crm update to assert operational rollback."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Rollback", "phone": "54321", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Patch run_in_transaction cursor to execute an error when updating crm_leads
        from unittest.mock import patch
        from system_app.crm.queries import run_in_transaction

        original_run = run_in_transaction
        def mock_run(callback, *args, **kwargs):
            def callback_wrapper(cur):
                # We execute the callback but patch cur.execute to fail on crm_leads update
                orig_execute = cur.execute
                def mock_execute(query, vars=None):
                    if "UPDATE crm_leads" in query:
                        query = query.replace("UPDATE crm_leads", "UPDATE invalid_table_trigger_rollback")
                    return orig_execute(query, vars)
                cur.execute = mock_execute
                return callback(cur)
            return original_run(callback_wrapper, *args, **kwargs)

        with patch('system_app.crm.services.run_in_transaction', side_effect=mock_run):
            r = self.client.post(f'/crm/leads/{lead_id}/convert', json={"membership_packages": "1 Month", "starting_date": "2026-08-15"})
            self.assertEqual(r.status_code, 500)

        # Verify member was not created (rolled back)
        member = query_db("SELECT * FROM members WHERE phone = '54321'", one=True)
        self.assertIsNone(member)

        # Verify invoice was not created
        inv = query_db("SELECT * FROM invoices WHERE member_name = 'Test Rollback'", one=True)
        self.assertIsNone(inv)

    # ==========================================
    # G. NEW ERROR-MAPPING TESTS
    # ==========================================

    def test_13_invalid_national_id_returns_400(self):
        """TEST 13: Invalid national_id format returns 400 invalid_input, NOT 409 duplicate_member."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Bad ID", "phone": "1313", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15",
            "national_id": "12345"  # Invalid ( Egypt National ID needs 14 digits )
        })
        self.assertEqual(res_conv.status_code, 400)
        self.assertEqual(res_conv.get_json()['error'], 'invalid_input')

    def test_14_missing_required_member_data_returns_400(self):
        """TEST 14: Missing package data returns 400 invalid_input."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test Missing package", "phone": "1414", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={
            "starting_date": "2026-08-15"
        })
        self.assertEqual(res_conv.status_code, 400)
        self.assertEqual(res_conv.get_json()['error'], 'invalid_input')

    def test_15_db_unique_violation_maps_to_409(self):
        """TEST 15: Database UniqueViolation constraint (e.g. duplicate key) returns 409 duplicate_member."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test DB Unique", "phone": "1515", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Pre-create member with national_id '12345678901234' directly in members bypass checks
        query_db(
            "INSERT INTO members (name, phone, national_id, membership_packages, starting_date) "
            "VALUES ('Test Preexisting', '1515', '12345678901234', '1 Month', '2026-08-15');", commit=True
        )

        # Mock the business-level duplicate check to simulate it being bypassed and falling back to DB constraint
        import psycopg2
        from unittest.mock import patch
        with patch('system_app.member_services.validate_national_id', return_value=True):
            # We mock the cursor fetch to return None for duplicates checking
            original_execute = psycopg2.extras.RealDictCursor.execute
            def mock_execute(self_cursor, query, vars=None):
                if "SELECT id FROM members WHERE" in query:
                    # Return no duplicate in Python so it proceeds to INSERT
                    return original_execute(self_cursor, "SELECT NULL LIMIT 0")
                return original_execute(self_cursor, query, vars)

            with patch('psycopg2.extras.RealDictCursor.execute', mock_execute):
                res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={
                    "membership_packages": "1 Month",
                    "starting_date": "2026-08-15",
                    "national_id": "12345678901234"
                })
                self.assertEqual(res_conv.status_code, 409)
                self.assertEqual(res_conv.get_json()['error'], 'duplicate_member')

    def test_16_unexpected_db_failure_propagates_500(self):
        """TEST 16: Unexpected DB exception does not map to duplicate_member and returns 500."""
        self.login_as('crm_converter', 20002)
        res = self.client.post('/crm/leads', json={"name": "Test DB Fail", "phone": "1616", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Force a generic database error (e.g. invalid syntax)
        import psycopg2
        from unittest.mock import patch
        original_execute = psycopg2.extras.RealDictCursor.execute
        def mock_execute(self_cursor, query, vars=None):
            if "INSERT INTO members" in query:
                return original_execute(self_cursor, "SELECT * FROM nonexistent_table_triggering_generic_db_error")
            return original_execute(self_cursor, query, vars)

        with patch('psycopg2.extras.RealDictCursor.execute', mock_execute):
            res_conv = self.client.post(f'/crm/leads/{lead_id}/convert', json={
                "membership_packages": "1 Month",
                "starting_date": "2026-08-15"
            })
            self.assertEqual(res_conv.status_code, 500)

if __name__ == '__main__':
    unittest.main()
