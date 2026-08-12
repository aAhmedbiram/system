"""
test_crm_phase2c2.py — CRM Phase 2C-2 Activity Composer + Follow-up Scheduling Tests

Tests:
  A. POST activity permissions and access control
  B. User-submittable activity types
  C. System activity types rejected by POST
  D. Follow-up semantics (omit / null / timestamp)
  E. Datetime validation (naive, past, malformed)
  F. FOLLOW_UP_CLEARED behavior
  G. Timeline ordering and integration
  H. Template / JS static assertions
  I. XSS safety
  J. Regression
"""

import os
import re
import datetime
import unittest
from system_app.app import app
from system_app.queries import query_db


FUTURE_TS = "2099-12-31T23:59:00+03:00"
PAST_TS   = "2000-01-01T10:00:00+03:00"


class TestCRMPhase2C2(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db(
            "DELETE FROM users WHERE username IN ('rino','c2_view','c2_edit','c2_none')",
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',    'rino@test.com', 'pwd', TRUE, '{}'),
            (40001, 'c2_view', 'v@c2.com',      'pwd', TRUE, '{"crm_view": true}'),
            (40002, 'c2_edit', 'e@c2.com',      'pwd', TRUE,
              '{"crm_view": true, "crm_edit": true}'),
            (40003, 'c2_none', 'n@c2.com',      'pwd', TRUE, '{}')
        """, commit=True)

        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 40001, 40002, 40003)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _create_lead(self, lead_id, assigned_user_id=None, follow_up_at=None):
        query_db(
            "INSERT INTO crm_leads (id, name, phone, source, stage, "
            "assigned_user_id, next_follow_up_at) VALUES (%s,%s,%s,'WALK_IN','NEW',%s,%s)",
            (lead_id, f"Lead {lead_id}", f"0{lead_id}", assigned_user_id, follow_up_at),
            commit=True
        )

    # ==================================================================
    # A. POST ACTIVITY PERMISSIONS
    # ==================================================================

    def test_01_unauthenticated_blocked(self):
        """Unauthenticated POST is blocked."""
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL"})
        self.assertEqual(res.status_code, 302)

    def test_02_crm_view_only_cannot_post(self):
        """crm_view only user cannot POST activities."""
        self.login_as('c2_view', 40001)
        self._create_lead(6001, assigned_user_id=40001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL"})
        # crm_edit required — should redirect or 302
        self.assertIn(res.status_code, [302, 403])

    def test_03_no_permission_user_blocked(self):
        """User without any CRM permission blocked from POST."""
        self.login_as('c2_none', 40003)
        self._create_lead(6001, assigned_user_id=40003)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL"})
        self.assertIn(res.status_code, [302, 403])

    def test_04_crm_edit_can_post_own_lead(self):
        """crm_edit user can POST activity on their own lead."""
        self.login_as('c2_edit', 40002)
        self._create_lead(6001, assigned_user_id=40002)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL", "note": "Hello"})
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.get_json()['status'], 'created')

    def test_05_hidden_lead_denied(self):
        """crm_edit user denied activity on lead assigned to someone else."""
        self.login_as('c2_edit', 40002)
        self._create_lead(6002, assigned_user_id=40001)  # assigned to view user
        res = self.client.post('/crm/leads/6002/activities',
                               json={"activity_type": "CALL"})
        self.assertEqual(res.status_code, 403)

    def test_06_rino_can_post_any_lead(self):
        """rino (super admin) can POST activity on any lead."""
        self.login_as('rino', 2)
        self._create_lead(6001, assigned_user_id=40001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "NOTE", "note": "Rino note"})
        self.assertEqual(res.status_code, 201)

    # ==================================================================
    # B. USER-SUBMITTABLE ACTIVITY TYPES
    # ==================================================================

    def test_07_type_call_accepted(self):
        """CALL is a valid user-submittable type."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL", "note": "Call"})
        self.assertEqual(res.status_code, 201)

    def test_08_type_whatsapp_accepted(self):
        """WHATSAPP is a valid user-submittable type."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "WHATSAPP"})
        self.assertEqual(res.status_code, 201)

    def test_09_type_visit_accepted(self):
        """VISIT is a valid user-submittable type."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "VISIT", "note": "Visited"})
        self.assertEqual(res.status_code, 201)

    def test_10_type_note_accepted(self):
        """NOTE is a valid user-submittable type."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "NOTE", "note": "Internal"})
        self.assertEqual(res.status_code, 201)

    def test_11_type_follow_up_with_note_accepted(self):
        """FOLLOW_UP with note is valid."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "FOLLOW_UP", "note": "Call tomorrow"})
        self.assertEqual(res.status_code, 201)

    def test_12_type_follow_up_with_timestamp_accepted(self):
        """FOLLOW_UP with future timestamp is valid."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "FOLLOW_UP",
            "next_follow_up_at": FUTURE_TS
        })
        self.assertEqual(res.status_code, 201)

    def test_13_type_follow_up_without_note_or_ts_rejected(self):
        """FOLLOW_UP without note or timestamp is rejected."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "FOLLOW_UP"})
        self.assertEqual(res.status_code, 400)

    # ==================================================================
    # C. SYSTEM ACTIVITY TYPES REJECTED
    # ==================================================================

    def test_14_stage_change_rejected(self):
        """STAGE_CHANGE not user-submittable via POST activities endpoint."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "STAGE_CHANGE"})
        self.assertEqual(res.status_code, 400)

    def test_15_assigned_rejected(self):
        """ASSIGNED not user-submittable."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "ASSIGNED"})
        self.assertEqual(res.status_code, 400)

    def test_16_converted_rejected(self):
        """CONVERTED not user-submittable."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CONVERTED"})
        self.assertEqual(res.status_code, 400)

    def test_17_lost_rejected(self):
        """LOST not user-submittable via activities endpoint."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "LOST"})
        self.assertEqual(res.status_code, 400)

    def test_18_unknown_type_rejected(self):
        """Completely unknown activity type rejected."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "SOME_FUTURE_TYPE"})
        self.assertEqual(res.status_code, 400)

    # ==================================================================
    # D. FOLLOW-UP SEMANTICS
    # ==================================================================

    def test_19_omit_followup_key_preserves_current(self):
        """Omitting next_follow_up_at preserves the existing scheduled follow-up."""
        self.login_as('rino', 2)
        self._create_lead(6001, follow_up_at=FUTURE_TS)
        # Post without next_follow_up_at key
        self.client.post('/crm/leads/6001/activities',
                         json={"activity_type": "NOTE", "note": "Just a note"})
        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = 6001", one=True)
        self.assertIsNotNone(lead['next_follow_up_at'],
                             "Follow-up should not have been cleared when key was omitted")

    def test_20_explicit_null_clears_followup(self):
        """Sending next_follow_up_at: null explicitly clears the follow-up."""
        self.login_as('rino', 2)
        self._create_lead(6001, follow_up_at=FUTURE_TS)
        self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "NOTE",
            "note": "Clearing",
            "next_follow_up_at": None
        })
        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = 6001", one=True)
        self.assertIsNone(lead['next_follow_up_at'],
                          "Follow-up should have been cleared")

    def test_21_valid_future_ts_sets_followup(self):
        """Valid future tz-aware timestamp sets next_follow_up_at on lead."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": FUTURE_TS
        })
        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = 6001", one=True)
        self.assertIsNotNone(lead['next_follow_up_at'])

    # ==================================================================
    # E. DATETIME VALIDATION
    # ==================================================================

    def test_22_naive_timestamp_rejected(self):
        """Timezone-naive ISO timestamp is rejected."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "2099-12-31T23:59:00"  # no offset
        })
        self.assertEqual(res.status_code, 400)

    def test_23_past_timestamp_rejected(self):
        """Past timestamp is rejected."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": PAST_TS
        })
        self.assertEqual(res.status_code, 400)

    def test_24_malformed_timestamp_rejected(self):
        """Malformed timestamp string is rejected."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        res = self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "not-a-date"
        })
        self.assertEqual(res.status_code, 400)

    # ==================================================================
    # F. FOLLOW_UP_CLEARED BEHAVIOR
    # ==================================================================

    def test_25_cleared_marker_stored_when_null_sent(self):
        """Sending explicit null creates FOLLOW_UP_CLEARED marker in activity result."""
        self.login_as('rino', 2)
        self._create_lead(6001, follow_up_at=FUTURE_TS)
        self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "NOTE",
            "next_follow_up_at": None
        })
        act = query_db(
            "SELECT result FROM crm_activities WHERE lead_id = 6001 ORDER BY id DESC LIMIT 1",
            one=True
        )
        self.assertIsNotNone(act)
        self.assertIn("FOLLOW_UP_CLEARED", act['result'])

    def test_26_cleared_marker_combined_with_user_result(self):
        """When result text + clear null sent, marker appended to result."""
        self.login_as('rino', 2)
        self._create_lead(6001, follow_up_at=FUTURE_TS)
        self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "NOTE",
            "result": "No longer needed",
            "next_follow_up_at": None
        })
        act = query_db(
            "SELECT result FROM crm_activities WHERE lead_id = 6001 ORDER BY id DESC LIMIT 1",
            one=True
        )
        self.assertIn("No longer needed", act['result'])
        self.assertIn("[FOLLOW_UP_CLEARED]", act['result'])

    # ==================================================================
    # G. TIMELINE ORDERING AND INTEGRATION
    # ==================================================================

    def test_27_new_activity_appears_in_timeline(self):
        """After POST, activity appears in GET activities response."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        self.client.post('/crm/leads/6001/activities', json={
            "activity_type": "WHATSAPP",
            "note": "Sent membership info"
        })
        res = self.client.get('/crm/leads/6001/activities')
        items = res.get_json()['items']
        self.assertTrue(any(i['activity_type'] == 'WHATSAPP' for i in items))
        self.assertTrue(any(i['note'] == 'Sent membership info' for i in items))

    def test_28_newest_first_ordering_preserved_after_post(self):
        """Timeline ordering remains newest-first after adding activities."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        self.client.post('/crm/leads/6001/activities',
                         json={"activity_type": "CALL", "note": "First"})
        self.client.post('/crm/leads/6001/activities',
                         json={"activity_type": "NOTE", "note": "Second"})
        items = self.client.get('/crm/leads/6001/activities').get_json()['items']
        ids = [i['id'] for i in items]
        self.assertEqual(ids, sorted(ids, reverse=True))

    def test_29_pagination_still_works_after_posts(self):
        """Pagination contract intact after multiple posts."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        for i in range(5):
            self.client.post('/crm/leads/6001/activities',
                             json={"activity_type": "NOTE", "note": f"n{i}"})
        data = self.client.get('/crm/leads/6001/activities?page=1&per_page=3').get_json()
        self.assertEqual(data['per_page'], 3)
        self.assertEqual(len(data['items']), 3)
        self.assertEqual(data['total'], 5)

    def test_30_archived_lead_rejects_activity(self):
        """Archived lead rejects new activity with 409."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        query_db("UPDATE crm_leads SET is_archived = TRUE WHERE id = 6001", commit=True)
        res = self.client.post('/crm/leads/6001/activities',
                               json={"activity_type": "CALL"})
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.get_json()['error'], 'lead_archived')

    # ==================================================================
    # H. TEMPLATE / JS STATIC ASSERTIONS
    # ==================================================================

    def test_31_composer_present_for_crm_edit(self):
        """Composer UI present in HTML for crm_edit user."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'activityComposer', res.data)
        self.assertIn(b'submitActivityBtn', res.data)
        self.assertIn(b'composerType', res.data)
        self.assertIn(b'composerNote', res.data)

    def test_32_composer_absent_for_view_only(self):
        """Composer UI absent in HTML for crm_view-only user."""
        self.login_as('c2_view', 40001)
        res = self.client.get('/crm/leads/6001/view')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'activityComposer', res.data)
        self.assertNotIn(b'submitActivityBtn', res.data)

    def test_33_crm_user_can_edit_flag_true_for_crm_edit(self):
        """CRM_USER_CAN_EDIT JS flag is true for crm_edit user."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'CRM_USER_CAN_EDIT = true', res.data)

    def test_34_crm_user_can_edit_flag_false_for_view_only(self):
        """CRM_USER_CAN_EDIT JS flag is false for crm_view-only user."""
        self.login_as('c2_view', 40001)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'CRM_USER_CAN_EDIT = false', res.data)

    def test_35_rino_gets_can_edit_true(self):
        """rino (super admin) gets CRM_USER_CAN_EDIT = true."""
        self.login_as('rino', 2)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'CRM_USER_CAN_EDIT = true', res.data)

    def test_36_clear_followup_btn_in_composer(self):
        """clearFollowUpBtn element present in template for crm_edit."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'clearFollowUpBtn', res.data)

    def test_37_only_user_types_in_composer_select(self):
        """Composer select contains only user-submittable types."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        data = res.data
        # User types must be present
        self.assertIn(b'value="CALL"', data)
        self.assertIn(b'value="WHATSAPP"', data)
        self.assertIn(b'value="VISIT"', data)
        self.assertIn(b'value="NOTE"', data)
        self.assertIn(b'value="FOLLOW_UP"', data)
        # System types must NOT be in the select options
        self.assertNotIn(b'value="STAGE_CHANGE"', data)
        self.assertNotIn(b'value="ASSIGNED"', data)
        self.assertNotIn(b'value="CONVERTED"', data)
        self.assertNotIn(b'value="LOST"', data)

    def test_38_js_has_double_submit_guard(self):
        """JS source contains double-submit guard pattern."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('isSubmitting', js)

    def test_39_js_refreshes_timeline_after_success(self):
        """JS calls reloadTimeline after successful POST."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('reloadTimeline', js)
        self.assertIn('window.reloadTimeline', js)

    def test_40_js_refreshes_lead_after_success(self):
        """JS calls reloadLead after successful POST."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('reloadLead', js)
        self.assertIn('window.reloadLead', js)

    def test_41_js_cairo_iso_conversion_present(self):
        """JS contains Cairo-aware ISO conversion logic (+03:00)."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('+03:00', js)
        self.assertIn('toCaroISO', js)

    def test_42_js_urgency_display_present(self):
        """JS contains urgency badge logic (overdue/today/upcoming)."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('renderFollowUpVal', js)
        self.assertIn('Overdue', js)
        self.assertIn('Today', js)
        self.assertIn('Upcoming', js)
        self.assertIn('Africa/Cairo', js)

    def test_43_js_does_not_force_full_page_reload(self):
        """JS refreshes data through reload helpers, not a full browser reload."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertNotIn('location.reload(', js)
        self.assertNotIn('window.location.reload', js)
        self.assertNotIn('window.location =', js)

    def test_44_js_followup_omits_key_when_untouched(self):
        """Composer source keeps next_follow_up_at omitted when the field is untouched."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('If neither: omit next_follow_up_at entirely', js)
        self.assertIn('payload.next_follow_up_at = null;', js)

    def test_45_js_explicit_clear_sends_null(self):
        """Composer source sends explicit null for clear-follow-up intent."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('clearIntentActive', js)
        self.assertIn('payload.next_follow_up_at = null;', js)

    def test_46_composer_feedback_element_present(self):
        """composerFeedback element present in HTML."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'composerFeedback', res.data)

    # ==================================================================
    # I. XSS SAFETY
    # ==================================================================

    def test_47_no_unsafe_innerhtml_in_js(self):
        """JS does not use innerHTML with dynamic data (only empty-clearing allowed)."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        for line in js.splitlines():
            if 'innerHTML' in line:
                is_safe_clear = re.search(r'''innerHTML\s*=\s*["']\s*["']''', line)
                self.assertIsNotNone(
                    is_safe_clear,
                    f"Unsafe innerHTML found: {line.strip()}"
                )

    def test_48_no_insertadjacenthtml_in_js(self):
        """JS does not use insertAdjacentHTML."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertNotIn('insertAdjacentHTML', js)

    def test_49_textcontent_used_for_composer_feedback(self):
        """JS composer uses textContent for feedback messages."""
        js_path = os.path.join(
            os.path.dirname(__file__),
            'system_app', 'static', 'js', 'crm_lead_detail.js'
        )
        with open(js_path) as f:
            js = f.read()
        self.assertIn('feedbackEl.textContent', js)

    # ==================================================================
    # J. REGRESSION
    # ==================================================================

    def test_50_edit_lead_patch_still_works(self):
        """Existing PATCH lead edit still works after Phase 2C-2 changes."""
        self.login_as('c2_edit', 40002)
        self._create_lead(6001, assigned_user_id=40002)
        res = self.client.patch('/crm/leads/6001', json={
            "name": "Updated Name",
            "phone": "999",
            "source": "INSTAGRAM"
        })
        self.assertEqual(res.status_code, 200)
        lead = query_db("SELECT name FROM crm_leads WHERE id = 6001", one=True)
        self.assertEqual(lead['name'], 'Updated Name')

    def test_51_timeline_still_loads_after_composer_added(self):
        """GET activities still works correctly after Phase 2C-2 changes."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        query_db("""
            INSERT INTO crm_activities (lead_id, user_id, user_username_snapshot, activity_type, note)
            VALUES (6001, 2, 'rino', 'CALL', 'Test call')
        """, commit=True)
        res = self.client.get('/crm/leads/6001/activities')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['items'][0]['activity_type'], 'CALL')

    def test_52_lead_detail_html_still_renders(self):
        """Lead detail HTML view still renders with all existing elements."""
        self.login_as('c2_view', 40001)
        res = self.client.get('/crm/leads/6001/view')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'detailsContainer', res.data)
        self.assertIn(b'activitySection', res.data)
        self.assertIn(b'activityList', res.data)
        self.assertIn(b'loadMoreActivitiesBtn', res.data)

    def test_53_edit_modal_still_present_for_crm_edit(self):
        """Edit Lead modal still present for crm_edit."""
        self.login_as('c2_edit', 40002)
        res = self.client.get('/crm/leads/6001/view')
        self.assertIn(b'editLeadModal', res.data)
        self.assertIn(b'openEditModalBtn', res.data)

    def test_54_phase2c1_pagination_regression(self):
        """Phase 2C-1 pagination contract still intact."""
        self.login_as('rino', 2)
        self._create_lead(6001)
        for i in range(7):
            query_db("""
                INSERT INTO crm_activities (lead_id, user_id, user_username_snapshot, activity_type)
                VALUES (6001, 2, 'rino', 'NOTE')
            """, commit=True)
        data = self.client.get('/crm/leads/6001/activities?page=1&per_page=3').get_json()
        self.assertEqual(data['total'], 7)
        self.assertEqual(data['pages'], 3)
        self.assertEqual(len(data['items']), 3)


if __name__ == '__main__':
    unittest.main()
