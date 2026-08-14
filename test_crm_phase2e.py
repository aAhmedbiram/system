from pathlib import Path
import unittest
from system_app.app import app
from system_app.queries import query_db

JS_DIR = Path(__file__).resolve().parent / "system_app" / "static" / "js"


class TestCRMPhase2E(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get('TESTING')
        self._old_secret_key = app.config.get('SECRET_KEY')
        self._old_csrf_enabled = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db("DELETE FROM users WHERE username IN ('rino', 'p2e_view', 'p2e_assign')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',     'rino@test.com', 'pwd', TRUE, '{}'),
            (42001, 'p2e_view', 'view@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (42002, 'p2e_assign', 'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_assign": true}')
        """, commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 42001, 42002)", commit=True)
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _create_lead(self, lead_id, follow_up_at, assigned_user_id=None, name=None):
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, created_by_user_id, assigned_user_id, next_follow_up_at) VALUES (%s, %s, %s, 'WALK_IN', 'NEW', %s, %s, %s)",
            (lead_id, name or f"Lead {lead_id}", f"0{lead_id}", 42002 if assigned_user_id == 42002 else 42001, assigned_user_id, follow_up_at),
            commit=True
        )

    def test_01_html_queue_page_access(self):
        self.login_as('p2e_view', 42001)
        res = self.client.get('/crm/follow-ups/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Follow-Up Queue', res.data)
        self.assertIn(b'queueTable', res.data)
        self.assertIn(b'queuePrevBtn', res.data)
        self.assertIn(b'queueNextBtn', res.data)

    def test_02_permission_enforced(self):
        res = self.client.get('/crm/follow-ups/view')
        self.assertEqual(res.status_code, 302)

    def test_03_dashboard_cards_link_to_queue(self):
        self.login_as('p2e_view', 42001)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'/crm/follow-ups/view?status=overdue', res.data)
        self.assertIn(b'/crm/follow-ups/view?status=today', res.data)
        self.assertIn(b'/crm/follow-ups/view?status=upcoming', res.data)

    def test_04_followup_summary_json_visibility(self):
        self.login_as('p2e_view', 42001)
        query_db("UPDATE crm_leads SET next_follow_up_at = CURRENT_TIMESTAMP WHERE id = 999999", commit=True)
        res = self.client.get('/crm/follow-ups/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('overdue', data)
        self.assertIn('today', data)
        self.assertIn('upcoming', data)

    def test_05_queue_json_ordering_and_pagination(self):
        self.login_as('p2e_assign', 42002)
        self._create_lead(7301, '2099-01-01T09:00:00+03:00', assigned_user_id=42002, name='Alpha')
        self._create_lead(7302, '2099-01-01T10:00:00+03:00', assigned_user_id=42002, name='Beta')
        self._create_lead(7303, '2099-01-01T11:00:00+03:00', assigned_user_id=42002, name='Gamma')
        res = self.client.get('/crm/follow-ups?status=upcoming&page=1&per_page=2')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['per_page'], 2)
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['items']), 2)
        follow_values = [row['next_follow_up_at'] for row in data['items']]
        self.assertLessEqual(follow_values[0], follow_values[1])

    def test_06_queue_filters_statuses(self):
        self.login_as('p2e_assign', 42002)
        self._create_lead(7310, '2000-01-01T08:00:00+03:00', assigned_user_id=42002, name='Overdue Lead')
        self._create_lead(7311, '2099-12-31T08:00:00+03:00', assigned_user_id=42002, name='Upcoming Lead')
        res_overdue = self.client.get('/crm/follow-ups?status=overdue')
        res_upcoming = self.client.get('/crm/follow-ups?status=upcoming')
        self.assertEqual(res_overdue.status_code, 200)
        self.assertEqual(res_upcoming.status_code, 200)

    def test_07_queue_html_safe_rendering_hooks(self):
        with (JS_DIR / 'crm_follow_up_queue.js').open() as f:
            js = f.read()
        self.assertIn('textContent', js)
        self.assertIn('createElement', js)
        self.assertNotIn('insertAdjacentHTML', js)
