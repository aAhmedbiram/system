"""
test_crm_phase2c1.py — CRM Phase 2C-1 Read-Only Activity Timeline Tests

Tests:
  A. API regression (auth, visibility, pagination contract, ordering)
  B. Activity types — all user + system types
  C. Pagination — bounded page 1, page 2, total/pages
  D. Presentation / static assertions (template structure, JS, XSS safety)
  E. XSS edge case
  F. Regression baseline
"""

import re
import os
import unittest
from system_app.app import app
from system_app.queries import query_db


class TestCRMPhase2C1(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db(
            "DELETE FROM users WHERE username IN ('rino', 'c1_view', 'c1_edit', 'c1_none')",
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',    'rino@test.com',   'pwd', TRUE, '{}'),
            (30001, 'c1_view', 'view@c1.com',     'pwd', TRUE, '{"crm_view": true}'),
            (30002, 'c1_edit', 'edit@c1.com',     'pwd', TRUE, '{"crm_view": true, "crm_edit": true}'),
            (30003, 'c1_none', 'none@c1.com',     'pwd', TRUE, '{}')
        """, commit=True)

        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 30001, 30002, 30003)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _create_lead(self, lead_id, assigned_user_id=None):
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id) "
            "VALUES (%s, %s, %s, 'WALK_IN', 'NEW', %s)",
            (lead_id, f"Lead {lead_id}", f"0{lead_id}", assigned_user_id),
            commit=True
        )

    def _insert_activity(self, lead_id, activity_type, note=None, result=None,
                         old_stage=None, new_stage=None,
                         old_user_id=None, new_user_id=None,
                         follow_up_at=None, user_id=30002, username_snap="c1_edit"):
        query_db("""
            INSERT INTO crm_activities
              (lead_id, user_id, user_username_snapshot, activity_type,
               note, result, old_stage, new_stage,
               old_assigned_user_id, new_assigned_user_id, follow_up_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (lead_id, user_id, username_snap, activity_type,
              note, result, old_stage, new_stage,
              old_user_id, new_user_id, follow_up_at), commit=True)

    # ==================================================================
    # A. API REGRESSION
    # ==================================================================

    def test_01_activities_requires_login(self):
        """GET /activities blocked for unauthenticated sessions."""
        self._create_lead(5001, 30001)
        res = self.client.get('/crm/leads/5001/activities')
        self.assertEqual(res.status_code, 302)

    def test_02_activities_requires_crm_view(self):
        """GET /activities blocked for user without crm_view."""
        self.login_as('c1_none', 30003)
        self._create_lead(5001, 30003)
        res = self.client.get('/crm/leads/5001/activities')
        self.assertEqual(res.status_code, 302)

    def test_03_crm_view_rino_can_access_activities(self):
        """rino can access activities of any visible lead."""
        self.login_as('rino', 2)
        self._create_lead(5001, 30001)
        self._insert_activity(5001, 'CALL', note='Test call')
        res = self.client.get('/crm/leads/5001/activities')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertIn('items', data)
        self.assertIn('total', data)
        self.assertIn('pages', data)
        self.assertIn('page', data)
        self.assertIn('per_page', data)

    def test_04_hidden_lead_denied_for_non_rino(self):
        """Non-rino user denied activities for lead assigned to someone else."""
        self.login_as('c1_view', 30001)
        self._create_lead(5002, 30002)
        self._insert_activity(5002, 'CALL')
        res = self.client.get('/crm/leads/5002/activities')
        self.assertEqual(res.status_code, 403)

    def test_05_pagination_contract_defaults(self):
        """Default pagination: page=1, per_page=25."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'NOTE', note='A')
        self._insert_activity(5001, 'NOTE', note='B')
        res = self.client.get('/crm/leads/5001/activities')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['per_page'], 25)
        self.assertEqual(data['total'], 2)
        self.assertEqual(data['pages'], 1)
        self.assertEqual(len(data['items']), 2)

    def test_06_pagination_respects_per_page_param(self):
        """per_page param is respected."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        for i in range(3):
            self._insert_activity(5001, 'NOTE', note=f'Note {i}')
        res = self.client.get('/crm/leads/5001/activities?page=1&per_page=2')
        data = res.get_json()
        self.assertEqual(data['per_page'], 2)
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['pages'], 2)

    def test_07_newest_first_ordering(self):
        """Activities returned newest-first (id DESC)."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'CALL', note='First call')
        self._insert_activity(5001, 'NOTE', note='Second note')
        self._insert_activity(5001, 'WHATSAPP', note='Third whatsapp')
        res = self.client.get('/crm/leads/5001/activities')
        items = res.get_json()['items']
        self.assertEqual(len(items), 3)
        ids = [i['id'] for i in items]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_08_activity_fields_present(self):
        """All expected fields present in each activity item."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'CALL', note='Hello', result='Answered')
        res = self.client.get('/crm/leads/5001/activities')
        item = res.get_json()['items'][0]
        for field in ['id', 'lead_id', 'user_id', 'user_username_snapshot',
                      'activity_type', 'note', 'result', 'old_stage', 'new_stage',
                      'old_assigned_user_id', 'new_assigned_user_id',
                      'follow_up_at', 'created_at']:
            self.assertIn(field, item, f"Missing field: {field}")

    def test_09_activities_404_for_missing_lead(self):
        """Returns 404 for a lead that does not exist."""
        self.login_as('rino', 2)
        res = self.client.get('/crm/leads/99999/activities')
        self.assertEqual(res.status_code, 404)

    # ==================================================================
    # B. ACTIVITY TYPES
    # ==================================================================

    def test_10_activity_type_call(self):
        """CALL activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'CALL', note='Called client')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'CALL')

    def test_11_activity_type_whatsapp(self):
        """WHATSAPP activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'WHATSAPP', note='Sent pricing')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'WHATSAPP')

    def test_12_activity_type_visit(self):
        """VISIT activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'VISIT', note='Walked in')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'VISIT')

    def test_13_activity_type_note(self):
        """NOTE activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'NOTE', note='Internal note')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'NOTE')

    def test_14_activity_type_follow_up(self):
        """FOLLOW_UP activity with scheduled time."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'FOLLOW_UP', note='Call tomorrow',
                              follow_up_at='2026-09-01T10:00:00+03:00')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'FOLLOW_UP')
        self.assertIsNotNone(items[0]['follow_up_at'])

    def test_15_activity_type_assigned(self):
        """ASSIGNED system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'ASSIGNED', old_user_id=None, new_user_id=30002,
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'ASSIGNED')
        self.assertEqual(items[0]['new_assigned_user_id'], 30002)

    def test_16_activity_type_stage_change(self):
        """STAGE_CHANGE system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'STAGE_CHANGE', old_stage='NEW', new_stage='CONTACTED',
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'STAGE_CHANGE')
        self.assertEqual(items[0]['old_stage'], 'NEW')
        self.assertEqual(items[0]['new_stage'], 'CONTACTED')

    def test_17_activity_type_lost(self):
        """LOST system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'LOST', old_stage='INTERESTED', new_stage='LOST',
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'LOST')

    def test_18_activity_type_reopened(self):
        """REOPENED system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'REOPENED', old_stage='LOST', new_stage='NEW',
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'REOPENED')

    def test_19_activity_type_converted(self):
        """CONVERTED system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'CONVERTED', note='Conversion complete',
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'CONVERTED')

    def test_20_activity_type_reactivated(self):
        """REACTIVATED system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'REACTIVATED', note='Membership renewed',
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'REACTIVATED')

    def test_21_activity_type_reassigned(self):
        """REASSIGNED system activity."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'REASSIGNED', old_user_id=30001, new_user_id=30002,
                              username_snap='rino', user_id=2)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['activity_type'], 'REASSIGNED')

    # ==================================================================
    # C. PAGINATION
    # ==================================================================

    def test_22_page1_bounded(self):
        """Page 1 returns at most per_page items."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        for i in range(5):
            self._insert_activity(5001, 'NOTE', note=f'note {i}')
        res = self.client.get('/crm/leads/5001/activities?page=1&per_page=3')
        data = res.get_json()
        self.assertEqual(len(data['items']), 3)
        self.assertEqual(data['page'], 1)
        self.assertEqual(data['pages'], 2)

    def test_23_page2_returns_older_rows(self):
        """Page 2 contains older items (lower IDs) than page 1."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        for i in range(4):
            self._insert_activity(5001, 'NOTE', note=f'note {i}')
        p1 = self.client.get('/crm/leads/5001/activities?page=1&per_page=2').get_json()
        p2 = self.client.get('/crm/leads/5001/activities?page=2&per_page=2').get_json()
        ids_p1 = [i['id'] for i in p1['items']]
        ids_p2 = [i['id'] for i in p2['items']]
        self.assertGreater(min(ids_p1), max(ids_p2))

    def test_24_total_pages_correct(self):
        """total and pages values are mathematically consistent."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        for i in range(7):
            self._insert_activity(5001, 'NOTE', note=f'note {i}')
        data = self.client.get('/crm/leads/5001/activities?page=1&per_page=3').get_json()
        self.assertEqual(data['total'], 7)
        self.assertEqual(data['pages'], 3)

    # ==================================================================
    # D. PRESENTATION / STATIC AUDIT
    # ==================================================================

    def test_25_detail_template_has_timeline_section(self):
        """Lead detail HTML shell includes timeline container elements."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'activitySection', res.data)
        self.assertIn(b'activityList', res.data)
        self.assertIn(b'activityLoading', res.data)
        self.assertIn(b'activityError', res.data)

    def test_26_js_fetches_activities_endpoint(self):
        """JS file contains the /activities endpoint fetch call."""
        import os
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path, 'r') as f:
            js_source = f.read()
        self.assertIn('/activities', js_source)
        self.assertIn('loadActivities', js_source)

    def test_27_load_more_button_exists_in_html(self):
        """HTML includes the Load More button element."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertIn(b'loadMoreActivitiesBtn', res.data)
        self.assertIn(b'Load More', res.data)

    def test_29_no_assignment_controls_in_2c1(self):
        """Phase 2C-1 template has no assignment UI."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertNotIn(b'assignLeadBtn', res.data)
        self.assertNotIn(b'assignModal', res.data)

    def test_30_no_stage_controls_in_2c1(self):
        """Phase 2C-1 template has no stage mutation UI."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertNotIn(b'stageSelect', res.data)
        self.assertNotIn(b'changeStageBtn', res.data)

    # ==================================================================
    # D2. FOLLOW_UP_CLEARED marker tests
    # ==================================================================

    def test_31_follow_up_cleared_standalone_stored_and_retrieved(self):
        """Standalone FOLLOW_UP_CLEARED in result field is retrievable from API."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'NOTE', result='FOLLOW_UP_CLEARED')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['result'], 'FOLLOW_UP_CLEARED')

    def test_32_follow_up_cleared_suffix_stored_and_retrieved(self):
        """FOLLOW_UP_CLEARED appended to user text is retrievable from API."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        self._insert_activity(5001, 'NOTE', result='Call went well [FOLLOW_UP_CLEARED]')
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        result = items[0]['result']
        self.assertIn('FOLLOW_UP_CLEARED', result)
        self.assertIn('Call went well', result)

    def test_33_js_contains_cleared_marker_constants(self):
        """JS source contains FOLLOW_UP_CLEARED constants and Follow-up cleared presentation."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path, 'r') as f:
            js_source = f.read()
        self.assertIn('FOLLOW_UP_CLEARED', js_source)
        self.assertIn('Follow-up cleared', js_source)
        self.assertIn('[FOLLOW_UP_CLEARED]', js_source)

    def test_34_parse_result_logic_standalone(self):
        """parseResult Python equivalent: standalone FOLLOW_UP_CLEARED yields cleared=True, userText=None."""
        CLEARED_STANDALONE = "FOLLOW_UP_CLEARED"
        CLEARED_SUFFIX = " [FOLLOW_UP_CLEARED]"

        def parse_result(r):
            if not r:
                return {"userText": None, "cleared": False}
            if r == CLEARED_STANDALONE:
                return {"userText": None, "cleared": True}
            if r.endswith(CLEARED_SUFFIX):
                ut = r[:-len(CLEARED_SUFFIX)].strip() or None
                return {"userText": ut, "cleared": True}
            return {"userText": r, "cleared": False}

        r = parse_result("FOLLOW_UP_CLEARED")
        self.assertIsNone(r["userText"])
        self.assertTrue(r["cleared"])

        r = parse_result("Great call [FOLLOW_UP_CLEARED]")
        self.assertEqual(r["userText"], "Great call")
        self.assertTrue(r["cleared"])

        r = parse_result(" [FOLLOW_UP_CLEARED]")
        self.assertIsNone(r["userText"])
        self.assertTrue(r["cleared"])

        r = parse_result("Client answered")
        self.assertEqual(r["userText"], "Client answered")
        self.assertFalse(r["cleared"])

        r = parse_result(None)
        self.assertFalse(r["cleared"])

    # ==================================================================
    # E. XSS SAFETY
    # ==================================================================

    def test_35_xss_note_returned_as_json_data(self):
        """Script-like note returned safely as JSON data (not interpreted)."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        xss_note = '<script>alert("xss")</script>'
        self._insert_activity(5001, 'NOTE', note=xss_note)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(items[0]['note'], xss_note)

    def test_36_no_unsafe_innerhtml_in_js(self):
        """JS source does not use innerHTML to interpolate activity field data."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path, 'r') as f:
            js_source = f.read()

        innerhtml_uses = [
            line.strip() for line in js_source.splitlines()
            if 'innerHTML' in line
        ]

        for use in innerhtml_uses:
            is_empty_clear = re.search(r'''innerHTML\s*=\s*["']\s*["']''', use)
            self.assertIsNotNone(
                is_empty_clear,
                f"Unsafe innerHTML usage found: {use}"
            )

    def test_37_no_insertadjacenthtml_in_js(self):
        """JS source does not use insertAdjacentHTML."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path, 'r') as f:
            js_source = f.read()
        self.assertNotIn('insertAdjacentHTML', js_source)

    def test_38_textcontent_used_in_timeline_js(self):
        """JS timeline module uses textContent for safe DOM insertion."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path, 'r') as f:
            js_source = f.read()
        self.assertIn('textContent', js_source)

    # ==================================================================
    # F. REGRESSION
    # ==================================================================

    def test_39_lead_profile_json_api_intact(self):
        """Existing lead profile JSON API still returns correctly."""
        self.login_as('rino', 2)
        self._create_lead(5001, assigned_user_id=30002)
        res = self.client.get('/crm/leads/5001')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.get_json()['id'], 5001)

    def test_40_html_detail_view_loads(self):
        """Lead detail HTML view still renders."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'detailsContainer', res.data)

    def test_41_edit_modal_present_for_crm_edit(self):
        """Edit Lead modal still present for crm_edit user."""
        self.login_as('c1_edit', 30002)
        res = self.client.get('/crm/leads/5001/view')
        self.assertIn(b'editLeadModal', res.data)
        self.assertIn(b'openEditModalBtn', res.data)

    def test_42_edit_modal_hidden_for_view_only(self):
        """Edit Lead modal NOT present for view-only user."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertNotIn(b'openEditModalBtn', res.data)

    def test_43_empty_timeline_total_zero(self):
        """Lead with no activities returns total=0 and empty items list."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        data = self.client.get('/crm/leads/5001/activities').get_json()
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['items'], [])

    def test_44_null_username_snapshot_handled(self):
        """Activity with null user_username_snapshot still returned."""
        self.login_as('rino', 2)
        self._create_lead(5001)
        query_db("""
            INSERT INTO crm_activities (lead_id, user_id, user_username_snapshot, activity_type)
            VALUES (5001, NULL, NULL, 'CONVERTED')
        """, commit=True)
        items = self.client.get('/crm/leads/5001/activities').get_json()['items']
        self.assertEqual(len(items), 1)
        self.assertIsNone(items[0]['user_username_snapshot'])
        self.assertEqual(items[0]['activity_type'], 'CONVERTED')

    def test_45_activity_count_badge_in_template(self):
        """Template includes activityCountBadge element."""
        self.login_as('c1_view', 30001)
        res = self.client.get('/crm/leads/5001/view')
        self.assertIn(b'activityCountBadge', res.data)


if __name__ == '__main__':
    unittest.main()
