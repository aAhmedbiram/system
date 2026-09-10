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

    def test_08_restricted_user_follow_up_queue_with_campaigns_and_pagination(self):
        """Regression test for restricted users loading follow-up queue with campaigns linked, permission filtering, and count pagination."""
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns WHERE id = 90001", commit=True)
        query_db("INSERT INTO crm_campaigns (id, name, created_by_user_id) VALUES (90001, 'Promo Campaign', 42001)", commit=True)

        import datetime
        from system_app.crm.services import CAIRO_TZ
        now_cairo = datetime.datetime.now(CAIRO_TZ)
        today_start = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)
        overdue_dt = now_cairo - datetime.timedelta(days=2)
        # Ensure today_dt is strictly in the future relative to now_cairo but inside today's calendar day
        today_dt = now_cairo + ((today_end - now_cairo) / 2)
        upcoming_dt = today_end + datetime.timedelta(days=2)

        # 1. Create leads linked to campaign 90001
        # Lead 8001: Overdue, assigned to p2e_view (42001)
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, created_by_user_id, assigned_user_id, campaign_id, next_follow_up_at) VALUES (8001, 'Overdue Mine', '08001', 'WALK_IN', 'NEW', 42001, 42001, 90001, %s)",
            (overdue_dt,), commit=True
        )
        # Lead 8002: Today, created by p2e_view (42001) and unassigned
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, created_by_user_id, assigned_user_id, campaign_id, next_follow_up_at) VALUES (8002, 'Today Created Mine', '08002', 'WALK_IN', 'NEW', 42001, NULL, 90001, %s)",
            (today_dt,), commit=True
        )
        # Lead 8003: Upcoming, assigned to p2e_assign (42002), created by 42002
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, created_by_user_id, assigned_user_id, campaign_id, next_follow_up_at) VALUES (8003, 'Upcoming Other User', '08003', 'WALK_IN', 'NEW', 42002, 42002, 90001, %s)",
            (upcoming_dt,), commit=True
        )

        # 2. Test restricted user p2e_view (without CRM_ALL_LEADS)
        self.login_as('p2e_view', 42001)

        # Overdue queue -> 200 OK, returns Lead 8001
        res_overdue = self.client.get('/crm/follow-ups?status=overdue')
        self.assertEqual(res_overdue.status_code, 200)
        data_overdue = res_overdue.get_json()
        self.assertEqual(data_overdue['total'], 1)
        self.assertEqual(data_overdue['items'][0]['id'], 8001)
        self.assertEqual(data_overdue['items'][0]['campaign_name'], 'Promo Campaign')

        # Today queue -> 200 OK, returns Lead 8002
        res_today = self.client.get('/crm/follow-ups?status=today')
        self.assertEqual(res_today.status_code, 200)
        data_today = res_today.get_json()
        self.assertEqual(data_today['total'], 1)
        self.assertEqual(data_today['items'][0]['id'], 8002)

        # Upcoming queue -> 200 OK, Lead 8003 is NOT visible to p2e_view
        res_upcoming = self.client.get('/crm/follow-ups?status=upcoming')
        self.assertEqual(res_upcoming.status_code, 200)
        data_upcoming = res_upcoming.get_json()
        self.assertEqual(data_upcoming['total'], 0)
        self.assertEqual(len(data_upcoming['items']), 0)

        # 3. Test admin/super_admin user rino
        self.login_as('rino', 2)
        res_admin_upcoming = self.client.get('/crm/follow-ups?status=upcoming')
        self.assertEqual(res_admin_upcoming.status_code, 200)
        data_admin = res_admin_upcoming.get_json()
        self.assertEqual(data_admin['total'], 1)
        self.assertEqual(data_admin['items'][0]['id'], 8003)

        # Cleanup test campaign
        query_db("DELETE FROM crm_campaigns WHERE id = 90001", commit=True)
