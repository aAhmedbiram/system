from pathlib import Path
import unittest
from system_app.app import app
from system_app.queries import query_db

JS_DIR = Path(__file__).resolve().parent / "system_app" / "static" / "js"


class TestCRMPhase2D(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get('TESTING')
        self._old_secret_key = app.config.get('SECRET_KEY')
        self._old_csrf_enabled = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db("DELETE FROM users WHERE username IN ('rino', 'p2d_stage', 'p2d_assign', 'p2d_none')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',       'rino@test.com', 'pwd', TRUE, '{}'),
            (41001, 'p2d_stage',   'stage@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_update_stage": true}'),
            (41002, 'p2d_assign',  'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_assign": true}'),
            (41003, 'p2d_none',    'none@test.com', 'pwd', TRUE, '{}')
        """, commit=True)
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 41001, 41002, 41003)", commit=True)
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _create_lead(self, lead_id, created_by_user_id=None, assigned_user_id=None):
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, created_by_user_id, assigned_user_id) VALUES (%s, %s, %s, 'WALK_IN', 'NEW', %s, %s)",
            (lead_id, f"Lead {lead_id}", f"0{lead_id}", created_by_user_id, assigned_user_id),
            commit=True
        )

    def test_01_stage_controls_present_for_stage_user(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7001, created_by_user_id=41001)
        res = self.client.get('/crm/leads/7001/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'stageControlPanel', res.data)
        self.assertIn(b'stageSelect', res.data)
        self.assertIn(b'lostReasonSelect', res.data)
        self.assertIn(b'reopenLeadBtn', res.data)
        self.assertNotIn(b'value="WON"', res.data)
        self.assertIn(b'<meta name="csrf-token"', res.data)

    def test_02_assignment_controls_present_for_assign_user(self):
        self.login_as('p2d_assign', 41002)
        self._create_lead(7002, created_by_user_id=41002)
        res = self.client.get('/crm/leads/7002/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'assignmentControlPanel', res.data)
        self.assertIn(b'assignLeadBtn', res.data)
        self.assertIn(b'unassignLeadBtn', res.data)

    def test_03_active_stage_transition_logs_activity(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7003, created_by_user_id=41001)
        res = self.client.post('/crm/leads/7003/stage', json={'stage': 'CONTACTED'})
        self.assertEqual(res.status_code, 200)
        lead = query_db("SELECT stage FROM crm_leads WHERE id = 7003", one=True)
        self.assertEqual(lead['stage'], 'CONTACTED')
        activity = query_db("SELECT activity_type, old_stage, new_stage FROM crm_activities WHERE lead_id = 7003 ORDER BY id DESC LIMIT 1", one=True)
        self.assertEqual(activity['activity_type'], 'STAGE_CHANGE')
        self.assertEqual(activity['old_stage'], 'NEW')
        self.assertEqual(activity['new_stage'], 'CONTACTED')

    def test_04_lost_requires_reason(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7004, created_by_user_id=41001)
        res = self.client.post('/crm/leads/7004/stage', json={'stage': 'LOST'})
        self.assertEqual(res.status_code, 400)

    def test_05_lost_transition_clears_follow_up(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7005, created_by_user_id=41001)
        query_db("UPDATE crm_leads SET next_follow_up_at = CURRENT_TIMESTAMP WHERE id = 7005", commit=True)
        res = self.client.post('/crm/leads/7005/stage', json={'stage': 'LOST', 'lost_reason': 'PRICE'})
        self.assertEqual(res.status_code, 200)
        lead = query_db("SELECT stage, lost_reason, next_follow_up_at FROM crm_leads WHERE id = 7005", one=True)
        self.assertEqual(lead['stage'], 'LOST')
        self.assertEqual(lead['lost_reason'], 'PRICE')
        self.assertIsNone(lead['next_follow_up_at'])

    def test_06_manual_won_rejected(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7006, created_by_user_id=41001)
        res = self.client.post('/crm/leads/7006/stage', json={'stage': 'WON'})
        self.assertEqual(res.status_code, 400)

    def test_07_reopen_lost_defaults_to_follow_up(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7007, created_by_user_id=41001)
        self.client.post('/crm/leads/7007/stage', json={'stage': 'LOST', 'lost_reason': 'OTHER'})
        res = self.client.post('/crm/leads/7007/reopen', json={})
        self.assertEqual(res.status_code, 200)
        lead = query_db("SELECT stage, lost_reason FROM crm_leads WHERE id = 7007", one=True)
        self.assertEqual(lead['stage'], 'FOLLOW_UP')
        self.assertIsNone(lead['lost_reason'])

    def test_08_stage_permission_enforced(self):
        self.login_as('p2d_none', 41003)
        self._create_lead(7008, created_by_user_id=41003)
        res = self.client.post('/crm/leads/7008/stage', json={'stage': 'CONTACTED'})
        self.assertIn(res.status_code, [302, 403])

    def test_09_visibility_enforced_for_stage(self):
        self.login_as('p2d_stage', 41001)
        self._create_lead(7009, created_by_user_id=41001, assigned_user_id=41002)
        res = self.client.post('/crm/leads/7009/stage', json={'stage': 'CONTACTED'})
        self.assertEqual(res.status_code, 403)

    def test_10_assign_reassign_unassign_and_bulk_assign(self):
        self.login_as('p2d_assign', 41002)
        self._create_lead(7010, created_by_user_id=41002)
        self._create_lead(7011, created_by_user_id=41002)
        self._create_lead(7012, created_by_user_id=41002)

        users = self.client.get('/crm/users')
        self.assertEqual(users.status_code, 200)
        self.assertTrue(any(u['username'] == 'rino' for u in users.get_json()))

        assign = self.client.post('/crm/leads/7010/assign', json={'user_id': 41002})
        self.assertEqual(assign.status_code, 200)
        reassign = self.client.post('/crm/leads/7010/assign', json={'user_id': 2})
        self.assertEqual(reassign.status_code, 200)
        unassign = self.client.post('/crm/leads/7010/unassign', json={})
        self.assertEqual(unassign.status_code, 200)

        bulk = self.client.post('/crm/leads/bulk-assign', json={'lead_ids': [7011, 7012], 'user_id': 2})
        self.assertEqual(bulk.status_code, 200)
        rows = query_db("SELECT assigned_user_id FROM crm_leads WHERE id IN (7011, 7012) ORDER BY id")
        self.assertTrue(all(row['assigned_user_id'] == 2 for row in rows))

    def test_11_assignment_permission_enforced(self):
        self.login_as('p2d_none', 41003)
        self._create_lead(7013, created_by_user_id=41003)
        res = self.client.post('/crm/leads/7013/assign', json={'user_id': 2})
        self.assertIn(res.status_code, [302, 403])

    def test_12_dashboard_bulk_controls_present(self):
        self.login_as('p2d_assign', 41002)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'bulkAssignToolbar', res.data)
        self.assertIn(b'bulkAssignBtn', res.data)
        self.assertIn(b'selectAllLeads', res.data)

    def test_13_static_js_contains_csrf_and_double_submit_hooks(self):
        with (JS_DIR / 'crm_shared.js').open() as f:
            shared = f.read()
        with (JS_DIR / 'crm_lead_detail.js').open() as f:
            detail = f.read()
        with (JS_DIR / 'crm_leads.js').open() as f:
            leads = f.read()
        self.assertIn('X-CSRFToken', shared)
        self.assertIn('apiFetch', detail)
        self.assertIn('bulkAssignBtn', leads)
