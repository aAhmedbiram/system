import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase2A(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_user', 'regular_user')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_user', 'crm_user@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (20003, 'regular_user', 'regular_user@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

        # Clean crm tables
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM crm_activities", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    # ==========================================
    # A. CRM ROOT ROUTE
    # ==========================================

    def test_crm_root_unauthenticated_blocked(self):
        """CRM root denies access to unauthenticated sessions."""
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 302) # Redirect to login

    def test_crm_root_no_permission_blocked(self):
        """CRM root denies access to users without crm_view permission."""
        self.login_as('regular_user', 20003)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 302)

    def test_crm_root_rino_allowed_html(self):
        """rino bypasses permissions and gets the HTML dashboard layout."""
        self.login_as('rino', 2)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CRM Leads Dashboard', res.data)
        self.assertIn(b'leadsTable', res.data)

    def test_crm_root_crm_view_allowed_html(self):
        """User with crm_view gets the HTML dashboard layout."""
        self.login_as('crm_user', 20002)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'crm_leads.js', res.data)

    # ==========================================
    # B. SUMMARY & HEALTH JSON ENDPOINTS
    # ==========================================

    def test_crm_summary_json_works(self):
        """GET /crm/summary returns counts successfully."""
        self.login_as('crm_user', 20002)
        res = self.client.get('/crm/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('database_metrics', data)
        self.assertIn('leads', data['database_metrics'])
        self.assertIn('activities', data['database_metrics'])
        self.assertIn('campaigns', data['database_metrics'])

    def test_crm_health_works(self):
        """GET /crm/health check works correctly."""
        self.login_as('crm_user', 20002)
        res = self.client.get('/crm/health')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['status'], 'ok')

    # ==========================================
    # C. LEADS API & ASSIGNED USERNAME
    # ==========================================

    def test_leads_api_assigned_username(self):
        """Leads list API returns assigned_username successfully."""
        self.login_as('rino', 2)

        # Insert one assigned and one unassigned lead
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Lead Assigned', '123', 'WALK_IN', 'NEW', 20002), "
            "(102, 'Lead Unassigned', '456', 'WALK_IN', 'NEW', NULL)", commit=True
        )

        res = self.client.get('/crm/leads')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        items = data['items']

        self.assertEqual(len(items), 2)

        lead_assigned = next(x for x in items if x['id'] == 101)
        lead_unassigned = next(x for x in items if x['id'] == 102)

        self.assertEqual(lead_assigned['assigned_username'], 'crm_user')
        self.assertIsNone(lead_unassigned['assigned_username'])

if __name__ == '__main__':
    unittest.main()
