from pathlib import Path
import unittest
from system_app.app import app
from system_app.queries import query_db

JS_DIR = Path(__file__).resolve().parent / "system_app" / "static" / "js"


class TestCRMPhase2F(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get('TESTING')
        self._old_secret_key = app.config.get('SECRET_KEY')
        self._old_csrf_enabled = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db("DELETE FROM users WHERE username IN ('rino', 'p2f_convert', 'p2f_none')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',        'rino@test.com', 'pwd', TRUE, '{}'),
            (43001, 'p2f_convert', 'convert@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_convert": true}'),
            (43002, 'p2f_none',    'none@test.com', 'pwd', TRUE, '{}')
        """, commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs WHERE action_type = 'add_member'", commit=True)
        query_db("DELETE FROM members WHERE name ILIKE 'Phase2f%%'", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs WHERE action_type = 'add_member'", commit=True)
        query_db("DELETE FROM members WHERE name ILIKE 'Phase2f%%'", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 43001, 43002)", commit=True)
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _create_prospect_lead(self, lead_id):
        query_db(
            "INSERT INTO crm_leads (id, name, phone, email, source, stage, created_by_user_id) VALUES (%s, %s, %s, %s, 'WALK_IN', 'NEW', %s)",
            (lead_id, f"Phase2F Prospect {lead_id}", f"09{lead_id}", f"prospect{lead_id}@test.com", 43001),
            commit=True
        )

    def _create_member(self, member_id):
        query_db("""
            INSERT INTO members (id, name, phone, email, membership_status)
            VALUES (%s, %s, %s, %s, 'VAL')
        """, (member_id, f"Phase2F Member {member_id}", f"08{member_id}", f"member{member_id}@test.com"), commit=True)

    def _create_member_lead(self, lead_id, member_id):
        self._create_member(member_id)
        query_db(
            "INSERT INTO crm_leads (id, member_id, name, phone, email, source, stage, created_by_user_id) VALUES (%s, %s, %s, %s, %s, 'REFERRAL', 'NEW', %s)",
            (lead_id, member_id, f"Phase2F Member Lead {lead_id}", f"08{member_id}", f"member{member_id}@test.com", 43001),
            commit=True
        )

    def test_01_conversion_page_access(self):
        self.login_as('p2f_convert', 43001)
        self._create_prospect_lead(7401)
        res = self.client.get('/crm/leads/7401/convert/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Conversion Workspace', res.data)
        self.assertIn(b'convertForm', res.data)
        self.assertIn(b'convertBtn', res.data)
        self.assertIn(b'csrf-token', res.data)
        self.assertIn(b'crm_shared.js', res.data)

    def test_02_permission_enforced(self):
        self.login_as('p2f_none', 43002)
        self._create_prospect_lead(7402)
        res = self.client.get('/crm/leads/7402/convert/view')
        self.assertIn(res.status_code, [302, 403])

    def test_03_prospect_conversion_success(self):
        self.login_as('p2f_convert', 43001)
        self._create_prospect_lead(7403)
        res = self.client.post('/crm/leads/7403/convert', json={
            "starting_date": "2099-01-01",
            "membership_packages": "1 Month",
            "gender": "Male",
            "birthdate": "1990-01-01",
            "comment": "New member conversion"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['conversion_type'], 'new_member')
        lead = query_db("SELECT stage, member_id, converted_at, converted_by_user_id FROM crm_leads WHERE id = 7403", one=True)
        self.assertEqual(lead['stage'], 'WON')
        self.assertIsNotNone(lead['member_id'])
        act = query_db("SELECT activity_type, new_stage FROM crm_activities WHERE lead_id = 7403 ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual(act['activity_type'], 'CONVERTED')
        self.assertEqual(act['new_stage'], 'WON')
        invoice = query_db("SELECT * FROM invoices WHERE member_id = %s ORDER BY id DESC LIMIT 1", (lead['member_id'],), one=True)
        self.assertIsNotNone(invoice)

    def test_04_reactivation_conversion_success(self):
        self.login_as('p2f_convert', 43001)
        self._create_member_lead(7404, 8404)
        res = self.client.post('/crm/leads/7404/convert', json={
            "starting_date": "2099-01-01",
            "membership_packages": "3 Months"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['conversion_type'], 'reactivation')
        lead = query_db("SELECT stage, member_id FROM crm_leads WHERE id = 7404", one=True)
        self.assertEqual(lead['stage'], 'WON')
        self.assertEqual(lead['member_id'], 8404)
        act = query_db("SELECT activity_type FROM crm_activities WHERE lead_id = 7404 ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual(act['activity_type'], 'REACTIVATED')
        renewal = query_db("SELECT * FROM renewal_logs WHERE member_id = 8404 ORDER BY id DESC LIMIT 1", one=True)
        self.assertIsNotNone(renewal)

    def test_05_lost_archived_or_already_converted_blocked(self):
        self.login_as('p2f_convert', 43001)
        self._create_prospect_lead(7405)
        query_db("UPDATE crm_leads SET stage = 'LOST' WHERE id = 7405", commit=True)
        res_lost = self.client.post('/crm/leads/7405/convert', json={"starting_date": "2099-01-01", "membership_packages": "1 Month"})
        self.assertEqual(res_lost.status_code, 409)

        self._create_prospect_lead(7406)
        self.client.post('/crm/leads/7406/convert', json={"starting_date": "2099-01-01", "membership_packages": "1 Month"})
        res_again = self.client.post('/crm/leads/7406/convert', json={"starting_date": "2099-01-01", "membership_packages": "1 Month"})
        self.assertEqual(res_again.status_code, 409)

        self._create_prospect_lead(7407)
        query_db("UPDATE crm_leads SET is_archived = TRUE WHERE id = 7407", commit=True)
        res_archived = self.client.post('/crm/leads/7407/convert', json={"starting_date": "2099-01-01", "membership_packages": "1 Month"})
        self.assertEqual(res_archived.status_code, 409)

    def test_06_unauthorized_user_blocked(self):
        self.login_as('p2f_none', 43002)
        self._create_prospect_lead(7408)
        res = self.client.post('/crm/leads/7408/convert', json={"starting_date": "2099-01-01", "membership_packages": "1 Month"})
        self.assertIn(res.status_code, [302, 403])

    def test_07_js_static_guards(self):
        with (JS_DIR / 'crm_lead_convert.js').open() as f:
            js = f.read()
        self.assertIn('isSubmitting', js)
        self.assertIn('apiFetch', js)
        self.assertIn('convertBtn', js)
        self.assertIn('prospectFields', js)
