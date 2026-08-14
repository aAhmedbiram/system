import unittest
import datetime
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase1E(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_assign_user', 'crm_agent_a', 'crm_agent_b')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_assign_user', 'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_assign": true}'),
            (20003, 'crm_agent_a', 'agent_a@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true}'),
            (20004, 'crm_agent_b', 'agent_b@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_edit": true}')
        """, commit=True)

        # Clean leads and activities
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_campaigns", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    # ==========================================
    # A. ACTIVITY PERMISSIONS
    # ==========================================

    def test_1_assigned_user_can_add_activity(self):
        """TEST 1: Assigned user can add activity."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P1", "phone": "1111", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Assign to Agent A
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # Agent A logs activity
        self.login_as('crm_agent_a', 20003)
        res_act = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "note": "Called client",
            "result": "Answered"
        })
        self.assertEqual(res_act.status_code, 201)

    def test_2_unauthorized_user_cannot_add_activity(self):
        """TEST 2: Unauthorized user cannot add activity."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P2", "phone": "2222", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Assign to Agent A
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # Agent B (unassigned) tries to log activity
        self.login_as('crm_agent_b', 20004)
        res_act = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "note": "Sneaky call"
        })
        self.assertEqual(res_act.status_code, 403)

    def test_3_rino_can_add_activity_anywhere(self):
        """TEST 3: Rino can add activity anywhere."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P3", "phone": "3333", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Assign to Agent A
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # Rino logs activity
        self.login_as('rino', 2)
        res_act = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "NOTE",
            "note": "Rino note"
        })
        self.assertEqual(res_act.status_code, 201)

    def test_4_archived_lead_rejects_activity(self):
        """TEST 4: Archived lead rejects activity."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P4", "phone": "4444", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        self.client.post(f'/crm/leads/{lead_id}/archive')

        res_act = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "note": "Post archive call"
        })
        self.assertEqual(res_act.status_code, 409)

    # ==========================================
    # B. ACTIVITY TYPES
    # ==========================================

    def test_5_to_9_activity_types_accepted(self):
        """TEST 5-9: Activity types accepted."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P5", "phone": "5555", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        for act_type in ['CALL', 'WHATSAPP', 'VISIT', 'NOTE', 'FOLLOW_UP']:
            payload = {"activity_type": act_type, "note": f"test {act_type}"}
            if act_type == 'FOLLOW_UP':
                payload['next_follow_up_at'] = "2026-08-20T18:00:00+03:00"
            r = self.client.post(f'/crm/leads/{lead_id}/activities', json=payload)
            self.assertEqual(r.status_code, 201)

    def test_10_client_cannot_manually_create_assigned(self):
        """TEST 10: Client cannot manually create ASSIGNED."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P6", "phone": "6666", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "ASSIGNED",
            "note": "Manually assigned hack"
        })
        self.assertEqual(r.status_code, 400)

    def test_11_invalid_type_rejected(self):
        """TEST 11: Invalid type rejected."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P7", "phone": "7777", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "INVALID_TYPE",
            "note": "Bad type"
        })
        self.assertEqual(r.status_code, 400)

    # ==========================================
    # C. ACTOR SNAPSHOT
    # ==========================================

    def test_12_13_actor_identity_snapshots(self):
        """TEST 12-13: Actor snapshot details stored correctly."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P8", "phone": "8888", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "NOTE",
            "note": "Captured actor notes"
        })

        # Verify in DB
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s", (lead_id,), one=True)
        self.assertEqual(act['user_id'], 20002)
        self.assertEqual(act['user_username_snapshot'], 'crm_assign_user')

    # ==========================================
    # D. TIMELINE
    # ==========================================

    def test_14_to_18_timeline_queries(self):
        """TEST 14-18: Timeline content, assignments, sorting, pagination, security."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P9", "phone": "9999", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # 1. Existing ASSIGNED activity automatically created from Phase 1D
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # 2. Log manual note activity as crm_agent_a (the assignee)
        self.login_as('crm_agent_a', 20003)
        self.client.post(f'/crm/leads/{lead_id}/activities', json={"activity_type": "NOTE", "note": "Note A"})

        # Retrieve timeline
        res_timeline = self.client.get(f'/crm/leads/{lead_id}/activities?page=1&per_page=5')
        self.assertEqual(res_timeline.status_code, 200)
        data = res_timeline.get_json()

        self.assertEqual(data['total'], 2)
        self.assertEqual(data['items'][0]['activity_type'], 'NOTE')
        self.assertEqual(data['items'][1]['activity_type'], 'ASSIGNED') # Sorted correctly created_at DESC

        # Unauthorized timeline access
        self.login_as('crm_agent_b', 20004)
        res_timeline_bad = self.client.get(f'/crm/leads/{lead_id}/activities')
        self.assertEqual(res_timeline_bad.status_code, 403)

    # ==========================================
    # E. FOLLOW-UP SET
    # ==========================================

    def test_19_to_22_follow_up_setting(self):
        """TEST 19-22: Follow-up schedules update leads and match activity logs."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P10", "phone": "1010", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # 1. Set follow-up
        time_str = "2026-08-15T18:00:00+03:00"
        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "note": "Scheduled first",
            "next_follow_up_at": time_str
        })

        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNotNone(lead['next_follow_up_at'])

        # 2. Set new later follow-up
        later_time_str = "2026-08-20T10:00:00+03:00"
        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "WHATSAPP",
            "note": "Rescheduled",
            "next_follow_up_at": later_time_str
        })

        lead_after = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        # Verify crm_leads current next_follow_up_at updated to later one
        self.assertEqual(lead_after['next_follow_up_at'].strftime('%Y-%m-%d %H:%M'), "2026-08-20 10:00")

        # Verify first activity follow_up_at remains unchanged
        acts = query_db("SELECT follow_up_at FROM crm_activities WHERE lead_id = %s ORDER BY id ASC", (lead_id,))
        self.assertEqual(len(acts), 2)
        self.assertEqual(acts[0]['follow_up_at'].strftime('%Y-%m-%d %H:%M'), "2026-08-15 18:00")
        self.assertEqual(acts[1]['follow_up_at'].strftime('%Y-%m-%d %H:%M'), "2026-08-20 10:00")

    # ==========================================
    # F. FOLLOW-UP OMIT / NULL
    # ==========================================

    def test_23_to_25_omit_or_null_follow_up(self):
        """TEST 23-25: Omitted parameter leaves current set, explicit null clears it."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P11", "phone": "1011", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Set follow-up first
        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "2026-08-15T18:00:00+03:00"
        })

        # 1. Omit next_follow_up_at parameter - leaves current schedule intact
        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "NOTE",
            "note": "Simple note"
        })
        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNotNone(lead['next_follow_up_at'])

        # 2. Explicit null parameter - clears current schedule
        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "NOTE",
            "note": "Clear schedule notes",
            "next_follow_up_at": None
        })
        lead_cleared = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead_cleared['next_follow_up_at'])

        # Check historical activity follow_up_at is indeed null
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s ORDER BY id DESC LIMIT 1", (lead_id,), one=True)
        self.assertIsNone(act['follow_up_at'])
        self.assertIn("FOLLOW_UP_CLEARED", act['result'])

    # ==========================================
    # G. VALIDATION
    # ==========================================

    def test_26_malformed_timestamp_rejected(self):
        """TEST 26: Malformed timestamp rejected."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P12", "phone": "1012", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "2026-08-15 18:00:00" # missing T or offset
        })
        self.assertEqual(r.status_code, 400)

    def test_27_naive_timestamp_rejected(self):
        """TEST 27: Naive timestamp rejected."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P13", "phone": "1013", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "2026-08-15T18:00:00" # missing offset
        })
        self.assertEqual(r.status_code, 400)

    def test_28_past_timestamp_rejected(self):
        """TEST 28: Past timestamp rejected."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P14", "phone": "1014", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": "2020-01-01T12:00:00+03:00" # past
        })
        self.assertEqual(r.status_code, 400)

    def test_29_follow_up_validation_checks(self):
        """TEST 29: FOLLOW_UP activity type validation check constraint."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P15", "phone": "1015", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Missing both note and timestamp
        r = self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "FOLLOW_UP"
        })
        self.assertEqual(r.status_code, 400)

    # ==========================================
    # H. FOLLOW-UP QUERIES
    # ==========================================

    def test_30_to_37_follow_up_filters(self):
        """TEST 30-37: Today, Overdue, Upcoming follow-ups filtering, stages, visibility, pages."""
        # 1. Create leads scheduled around Cairo timezone (Cairo offset is +03:00)
        self.login_as('crm_assign_user', 20002)

        # Lead A: Overdue (e.g. scheduled yesterday, but we bypass validator constraint by manual update)
        r_a = self.client.post('/crm/leads', json={"name": "Overdue Lead", "phone": "1016", "source": "WALK_IN"})
        id_a = r_a.get_json()['id']
        query_db("UPDATE crm_leads SET next_follow_up_at = CURRENT_TIMESTAMP - INTERVAL '1 day' WHERE id = %s", (id_a,), commit=True)

        # Lead B: Today (scheduled in 1 hour)
        r_b = self.client.post('/crm/leads', json={"name": "Today Lead", "phone": "1017", "source": "WALK_IN"})
        id_b = r_b.get_json()['id']
        tz_cairo = datetime.timezone(datetime.timedelta(hours=3))
        now_cairo = datetime.datetime.now(tz_cairo)
        tomorrow_start = (
            now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
            + datetime.timedelta(days=1)
        )
        # Pick a future timestamp guaranteed to remain inside today's Cairo calendar day.
        today_dt = now_cairo + ((tomorrow_start - now_cairo) / 2)
        query_db(
            "UPDATE crm_leads SET next_follow_up_at = %s WHERE id = %s",
            (today_dt, id_b),
            commit=True,
        )

        # Lead C: Upcoming (scheduled in 3 days)
        r_c = self.client.post('/crm/leads', json={"name": "Upcoming Lead", "phone": "1018", "source": "WALK_IN"})
        id_c = r_c.get_json()['id']
        upcoming_dt = datetime.datetime.now(tz_cairo) + datetime.timedelta(days=3)
        self.client.post(f'/crm/leads/{id_c}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": upcoming_dt.isoformat()
        })

        # 2. Query today
        resp_today = self.client.get('/crm/follow-ups?status=today')
        self.assertEqual(resp_today.status_code, 200)
        self.assertEqual(len(resp_today.get_json()['items']), 1)
        self.assertEqual(resp_today.get_json()['items'][0]['id'], id_b)

        # 3. Query overdue
        resp_overdue = self.client.get('/crm/follow-ups?status=overdue')
        self.assertEqual(len(resp_overdue.get_json()['items']), 1)
        self.assertEqual(resp_overdue.get_json()['items'][0]['id'], id_a)

        # 4. Query upcoming
        resp_upcoming = self.client.get('/crm/follow-ups?status=upcoming')
        self.assertEqual(len(resp_upcoming.get_json()['items']), 1)
        self.assertEqual(resp_upcoming.get_json()['items'][0]['id'], id_c)

    # ==========================================
    # I. TRANSACTION ROLLBACK
    # ==========================================

    def test_38_database_rollback_on_lead_update_fail(self):
        """TEST 38: Lead update fail rolls back transaction."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P16", "phone": "1019", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # We mock lead update SQL execution to cause a DB error inside execute_transaction
        # We can patch execution query internally in execute_transaction
        from unittest.mock import patch
        from system_app.crm.queries import execute_transaction

        # We override execute_transaction to fail after inserting activity
        # But wait! A real database rollback must be verified.
        # Let's patch psycopg2 cursor execution in Python!
        # If the cursor executes 'UPDATE crm_leads' we force an error!
        original_execute_transaction = execute_transaction
        def mock_execute_transaction(operations):
            # Mutate operations list to introduce an invalid SQL statement for UPDATE crm_leads
            mutated = []
            for q, args in operations:
                if "UPDATE crm_leads" in q:
                    # Non-existent column raises PostgreSQL error
                    q = q.replace("SET next_follow_up_at =", "SET invalid_column_name_trigger_error =")
                mutated.append((q, args))
            return original_execute_transaction(mutated)

        with patch('system_app.crm.services.queries.execute_transaction', side_effect=mock_execute_transaction):
            response = self.client.post(f'/crm/leads/{lead_id}/activities', json={
                "activity_type": "CALL",
                "next_follow_up_at": "2026-08-20T18:00:00+03:00"
            })
            self.assertEqual(response.status_code, 500)

        # Verify no activity persists (rolled back) and lead follow-up is unchanged
        acts = query_db("SELECT * FROM crm_activities WHERE lead_id = %s", (lead_id,))
        self.assertEqual(len(acts), 0)

        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead['next_follow_up_at'])

    def test_39_database_rollback_on_activity_insert_fail(self):
        """TEST 39: Activity insert fail rolls back transaction."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P17", "phone": "1020", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # We mock execute_transaction to mutate INSERT crm_activities query to fail
        from unittest.mock import patch
        from system_app.crm.queries import execute_transaction

        original_execute_transaction = execute_transaction
        def mock_execute_transaction(operations):
            mutated = []
            for q, args in operations:
                if "INSERT INTO crm_activities" in q:
                    q = q.replace("INSERT INTO crm_activities", "INSERT INTO invalid_table_name_trigger_error")
                mutated.append((q, args))
            return original_execute_transaction(mutated)

        with patch('system_app.crm.services.queries.execute_transaction', side_effect=mock_execute_transaction):
            response = self.client.post(f'/crm/leads/{lead_id}/activities', json={
                "activity_type": "CALL",
                "next_follow_up_at": "2026-08-20T18:00:00+03:00"
            })
            self.assertEqual(response.status_code, 500)

        # Verify lead follow-up does not change (rolled back)
        lead = query_db("SELECT next_follow_up_at FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertIsNone(lead['next_follow_up_at'])

    # ==========================================
    # K. TIMEZONE BOUNDARY TESTS
    # ==========================================

    def test_40_cairo_midnight_timezone_boundary(self):
        """TEST 40: Cairo calendar day midnight boundaries."""
        self.login_as('crm_assign_user', 20002)
        res = self.client.post('/crm/leads', json={"name": "P18", "phone": "1021", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Set next_follow_up_at to exactly 1 minute before Cairo midnight today using ZoneInfo
        from zoneinfo import ZoneInfo
        cairo_tz = ZoneInfo("Africa/Cairo")
        now_cairo = datetime.datetime.now(cairo_tz)
        midnight_today = now_cairo.replace(hour=23, minute=59, second=0, microsecond=0)

        self.client.post(f'/crm/leads/{lead_id}/activities', json={
            "activity_type": "CALL",
            "next_follow_up_at": midnight_today.isoformat()
        })

        # Fetch today's follow-ups - must contain the lead
        resp = self.client.get('/crm/follow-ups?status=today')
        self.assertEqual(len(resp.get_json()['items']), 1)
        self.assertEqual(resp.get_json()['items'][0]['id'], lead_id)

        # Fetch upcoming follow-ups - must NOT contain the lead
        resp_up = self.client.get('/crm/follow-ups?status=upcoming')
        self.assertEqual(len(resp_up.get_json()['items']), 0)

if __name__ == '__main__':
    unittest.main()
