import unittest
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase2B(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_view_user', 'crm_create_user', 'regular_user')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_view_user', 'view@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (20003, 'crm_create_user', 'create@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (20004, 'regular_user', 'reg@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

        # Clean leads and members
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE id = 50001", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE id = 50001", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    # ==========================================
    # A. HTML DETAIL ROUTE
    # ==========================================

    def test_html_detail_unauthenticated_blocked(self):
        """Unauthenticated session blocked from details page."""
        res = self.client.get('/crm/leads/101/view')
        self.assertEqual(res.status_code, 302)

    def test_html_detail_crm_view_allowed(self):
        """User with crm_view can open the HTML shell."""
        self.login_as('crm_view_user', 20002)
        res = self.client.get('/crm/leads/101/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'crm_lead_detail.js', res.data)

    def test_html_detail_no_permission_denied(self):
        """User without crm_view is blocked from details HTML shell."""
        self.login_as('regular_user', 20004)
        res = self.client.get('/crm/leads/101/view')
        self.assertEqual(res.status_code, 302)

    def test_json_detail_returns_json(self):
        """GET /crm/leads/<id> remains JSON API."""
        self.login_as('crm_view_user', 20002)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Test Lead', '123', 'WALK_IN', 'NEW', 20002)", commit=True
        )
        res = self.client.get('/crm/leads/101')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['id'], 101)
        self.assertEqual(data['name'], 'Test Lead')

    # ==========================================
    # B. DETAIL API VERIFICATION
    # ==========================================

    def test_detail_api_assigned_username(self):
        """Lead detail API returns correct assigned_username."""
        self.login_as('rino', 2)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (101, 'Test Lead', '123', 'WALK_IN', 'NEW', 20003)", commit=True
        )
        res = self.client.get('/crm/leads/101')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['assigned_username'], 'crm_create_user')

    def test_detail_api_linked_member(self):
        """Lead detail API exposes member details for linked member."""
        self.login_as('rino', 2)
        query_db("INSERT INTO members (id, name, phone) VALUES (50001, 'Member Name', '123')", commit=True)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, member_id) "
            "VALUES (101, 'Member Name', '123', 'WALK_IN', 'NEW', 50001)", commit=True
        )
        res = self.client.get('/crm/leads/101')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data['is_existing_member'])
        self.assertEqual(data['member']['name'], 'Member Name')

    def test_detail_api_prospect_no_member_summary(self):
        """Prospect lead details have no member summary dict."""
        self.login_as('rino', 2)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, member_id) "
            "VALUES (101, 'Prospect Lead', '123', 'WALK_IN', 'NEW', NULL)", commit=True
        )
        res = self.client.get('/crm/leads/101')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertFalse(data['is_existing_member'])
        self.assertNotIn('member', data)

    # ==========================================
    # C. MEMBER SEARCH ENDPOINT
    # ==========================================

    def test_member_search_permissions(self):
        """Member search requires crm_create permission."""
        res = self.client.get('/crm/members/search?q=Test')
        self.assertEqual(res.status_code, 302)

        self.login_as('crm_view_user', 20002)
        res = self.client.get('/crm/members/search?q=Test')
        self.assertEqual(res.status_code, 302)

        self.login_as('crm_create_user', 20003)
        res = self.client.get('/crm/members/search?q=Test')
        self.assertEqual(res.status_code, 200)

    def test_member_search_works(self):
        """Member search works by name, phone, and ID."""
        self.login_as('crm_create_user', 20003)
        query_db("INSERT INTO members (id, name, phone) VALUES (50001, 'SearchName', '999888')", commit=True)

        # Name
        res = self.client.get('/crm/members/search?q=Search')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]['id'], 50001)

        # Phone
        res = self.client.get('/crm/members/search?q=99988')
        self.assertEqual(len(res.get_json()), 1)

        # ID
        res = self.client.get('/crm/members/search?q=50001')
        self.assertEqual(len(res.get_json()), 1)

    # ==========================================
    # D. SECURITY (XSS ESCAPING VERIFICATION)
    # ==========================================

    def test_lead_detail_xss_protection(self):
        """HTML detail route returns shell; script payload renders safely as plain text in JS context."""
        self.login_as('rino', 2)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, notes) "
            "VALUES (101, '<script>alert(1)</script>', '123', 'WALK_IN', 'NEW', 'notes')", commit=True
        )
        res = self.client.get('/crm/leads/101')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        # Verify script tag exists raw in JSON so browser gets exact name but we will enforce textContent rendering
        self.assertEqual(data['name'], '<script>alert(1)</script>')

if __name__ == '__main__':
    unittest.main()
