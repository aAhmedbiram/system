import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db
from system_app.crm.validators import VALID_LEAD_STAGES, VALID_ACTIVITY_TYPES
from system_app.crm.permissions import CRM_VIEW, CRM_ALL_LEADS

class TestCRMPhase1B(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    def test_1_blueprint_registered(self):
        """TEST 1: CRM Blueprint is registered."""
        rules = [r.rule for r in app.url_map.iter_rules()]
        self.assertIn('/crm/', rules)
        self.assertIn('/crm/health', rules)

    def test_2_unauthenticated_access_redirects(self):
        """TEST 2: Unauthenticated access to /crm/ is redirected."""
        response = self.client.get('/crm/')
        self.assertEqual(response.status_code, 302)
        self.assertIn('/login', response.location)

    def test_3_rino_can_access(self):
        """TEST 3: Rino can access /crm/."""
        # Find Rino ID
        rino = query_db("SELECT id FROM users WHERE username = 'rino'", one=True)
        if rino:
            rino_id = rino['id']
        else:
            rino_id = 99999
            query_db("DELETE FROM users WHERE id = 99999", commit=True)
            query_db("""
                INSERT INTO users (id, username, email, password, is_approved, permissions)
                VALUES (99999, 'rino', 'rino@test.com', 'pwd', TRUE, '{}')
            """, commit=True)

        with self.client.session_transaction() as sess:
            sess['user_id'] = rino_id
            sess['username'] = 'rino'

        response = self.client.get('/crm/')
        self.assertEqual(response.status_code, 200)

        if rino_id == 99999:
            query_db("DELETE FROM users WHERE id = 99999", commit=True)

    def test_4_user_without_crm_view_is_denied(self):
        """TEST 4: Regular user without crm_view is denied."""
        query_db("DELETE FROM users WHERE username = 'test_agent'", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (10001, 'test_agent', 'agent@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

        with self.client.session_transaction() as sess:
            sess['user_id'] = 10001
            sess['username'] = 'test_agent'

        response = self.client.get('/crm/')
        self.assertEqual(response.status_code, 302)

        # Cleanup
        query_db("DELETE FROM users WHERE id = 10001", commit=True)

    def test_5_user_with_crm_view_is_allowed(self):
        """TEST 5: Regular user with crm_view is allowed."""
        query_db("DELETE FROM users WHERE username = 'crm_agent'", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (10002, 'crm_agent', 'crm_agent@test.com', 'pwd', TRUE, '{"crm_view": true}')
        """, commit=True)

        with self.client.session_transaction() as sess:
            sess['user_id'] = 10002
            sess['username'] = 'crm_agent'

        response = self.client.get('/crm/summary')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['module'], 'crm')

        # Cleanup
        query_db("DELETE FROM users WHERE id = 10002", commit=True)

    def test_6_super_admin_is_allowed(self):
        """TEST 6: super_admin is allowed."""
        query_db("DELETE FROM users WHERE username = 'admin_user'", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (10003, 'admin_user', 'admin@test.com', 'pwd', TRUE, '{"super_admin": true}')
        """, commit=True)

        with self.client.session_transaction() as sess:
            sess['user_id'] = 10003
            sess['username'] = 'admin_user'

        response = self.client.get('/crm/summary')
        self.assertEqual(response.status_code, 200)

        # Cleanup
        query_db("DELETE FROM users WHERE id = 10003", commit=True)

    def test_7_health_endpoint(self):
        """TEST 7: /crm/health reaches service/query layer and confirms tables."""
        # 1. Unauthenticated -> Denied/Redirected
        client = app.test_client()
        response = client.get('/crm/health')
        self.assertEqual(response.status_code, 302)

        # 2. Authenticated but no crm_view -> Denied/Redirected
        query_db("DELETE FROM users WHERE username = 'test_agent'", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (10001, 'test_agent', 'agent@test.com', 'pwd', TRUE, '{}')
        """, commit=True)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 10001
            sess['username'] = 'test_agent'
        response = self.client.get('/crm/health')
        self.assertEqual(response.status_code, 302)
        query_db("DELETE FROM users WHERE id = 10001", commit=True)

        # 3. Authenticated with crm_view -> Allowed
        query_db("DELETE FROM users WHERE username = 'crm_agent'", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (10002, 'crm_agent', 'crm_agent@test.com', 'pwd', TRUE, '{"crm_view": true}')
        """, commit=True)
        with self.client.session_transaction() as sess:
            sess['user_id'] = 10002
            sess['username'] = 'crm_agent'
        response = self.client.get('/crm/health')
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(data['status'], 'ok')
        self.assertTrue(data['tables']['crm_leads'])
        query_db("DELETE FROM users WHERE id = 10002", commit=True)

    def test_8_validator_constants_match_db(self):
        """TEST 8: CRM constants match database stage/activity constraints."""
        self.assertEqual(len(VALID_LEAD_STAGES), 7)
        self.assertIn('NEW', VALID_LEAD_STAGES)
        self.assertIn('LOST', VALID_LEAD_STAGES)

        self.assertEqual(len(VALID_ACTIVITY_TYPES), 12)
        self.assertIn('CALL', VALID_ACTIVITY_TYPES)
        self.assertIn('REOPENED', VALID_ACTIVITY_TYPES)

if __name__ == '__main__':
    unittest.main()
