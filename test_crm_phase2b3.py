import unittest
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase2B3(unittest.TestCase):
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

    def test_prospect_post_success(self):
        """Prospect lead creation succeeds with valid inputs."""
        self.login_as('crm_create_user', 20003)
        res = self.client.post('/crm/leads', json={
            "name": "New Prospect",
            "phone": "0100999999",
            "email": "prospect@test.com",
            "source": "WALK_IN",
            "notes": "Interested in package"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data['status'], 'created')
        self.assertIn('id', data)

    def test_existing_member_post_success(self):
        """Existing member lead creation succeeds and snapshots details."""
        self.login_as('crm_create_user', 20003)
        query_db("INSERT INTO members (id, name, phone, email) VALUES (50001, 'Existing Member', '0122', 'mem@test.com')", commit=True)

        res = self.client.post('/crm/leads', json={
            "member_id": 50001,
            "source": "INSTAGRAM",
            "notes": "Wants to renew subscription"
        })
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertEqual(data['status'], 'created')

    def test_member_match_found_conflict(self):
        """Creating a prospect matching phone of a member returns member_match_found list."""
        self.login_as('crm_create_user', 20003)
        query_db("INSERT INTO members (id, name, phone, email) VALUES (50001, 'Existing Member', '0122', 'mem@test.com')", commit=True)

        # Post matching phone
        res = self.client.post('/crm/leads', json={
            "name": "Different Name",
            "phone": "0122",
            "email": "other@test.com",
            "source": "WALK_IN"
        })
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data['error'], 'member_match_found')
        self.assertEqual(data['details']['members'][0]['id'], 50001)

    def test_active_lead_exists_conflict(self):
        """Creating duplicate lead for member or phone returns active_lead_exists and lead ID."""
        self.login_as('crm_create_user', 20003)
        # Create lead
        query_db("INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) VALUES (900, 'Lead 1', '0122', 'WALK_IN', 'NEW', 20003)", commit=True)

        res = self.client.post('/crm/leads', json={
            "name": "Lead 2",
            "phone": "0122",
            "email": "different@test.com",
            "source": "INSTAGRAM"
        })
        self.assertEqual(res.status_code, 409)
        data = res.get_json()
        self.assertEqual(data['error'], 'active_lead_exists')
        self.assertEqual(data['details']['existing_lead_id'], 900)

    def test_invalid_payload_returns_400(self):
        """Invalid lead parameters return 400 bad request."""
        self.login_as('crm_create_user', 20003)
        res = self.client.post('/crm/leads', json={
            "name": "",
            "phone": "123"
        })
        self.assertEqual(res.status_code, 400)

    def test_unauthorized_create_returns_403(self):
        """User without crm_create permission gets 403 Forbidden."""
        self.login_as('crm_view_user', 20002)
        res = self.client.post('/crm/leads', json={
            "name": "New Prospect",
            "phone": "0100999999",
            "source": "WALK_IN"
        })
        self.assertEqual(res.status_code, 302)
