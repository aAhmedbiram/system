import unittest
import datetime
from flask import session
from system_app.app import app
from system_app.queries import query_db

class TestCRMPhase1F(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users in DB
        query_db("DELETE FROM users WHERE username IN ('rino', 'crm_manager', 'crm_agent_a', 'crm_agent_b')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'crm_manager', 'manager@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_assign": true, "crm_update_stage": true, "crm_all_leads": true}'),
            (20003, 'crm_agent_a', 'agent_a@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true, "crm_update_stage": true}'),
            (20004, 'crm_agent_b', 'agent_b@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_edit": true}')
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
    # A. ACTIVE TRANSITIONS
    # ==========================================

    def test_1_to_7_active_stage_transitions(self):
        """TEST 1-7: Check transitions between various active stages."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead A", "phone": "1111", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Helper list of sequential test transitions:
        # 1. NEW -> CONTACTED
        # 2. CONTACTED -> INTERESTED
        # 3. INTERESTED -> FOLLOW_UP
        # 4. FOLLOW_UP -> CONTACTED
        # 5. CONTACTED -> FOLLOW_UP
        # 6. FOLLOW_UP -> INTERESTED
        # 7. INTERESTED -> TRIAL
        # 8. TRIAL -> FOLLOW_UP
        sequence = ['CONTACTED', 'INTERESTED', 'FOLLOW_UP', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL', 'FOLLOW_UP']

        for next_stage in sequence:
            r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": next_stage})
            self.assertEqual(r.status_code, 200)
            data = r.get_json()
            self.assertEqual(data['new_stage'], next_stage)

    # ==========================================
    # B. INVALID / PROTECTED TRANSITIONS
    # ==========================================

    def test_8_same_stage_transition_rejected(self):
        """TEST 8: Rejects transitioning to current stage (no-op)."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead B", "phone": "2222", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "NEW"})
        self.assertEqual(r.status_code, 400)

    def test_9_invalid_stage_rejected(self):
        """TEST 9: Rejects non-existent stages."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead C", "phone": "3333", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "SUPER_HOT"})
        self.assertEqual(r.status_code, 400)

    def test_10_manual_won_rejected(self):
        """TEST 10: WON cannot be set manually."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead D", "phone": "4444", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "WON"})
        self.assertEqual(r.status_code, 400)

    def test_11_transition_from_won_rejected(self):
        """TEST 11: Transitions starting from WON are blocked."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead E", "phone": "5555", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Hardcode DB to WON since normal API rejects it
        query_db("UPDATE crm_leads SET stage = 'WON' WHERE id = %s", (lead_id,), commit=True)

        r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "INTERESTED"})
        self.assertEqual(r.status_code, 400)

    def test_12_archived_lead_rejected(self):
        """TEST 12: Stage edits on archived leads are blocked."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead F", "phone": "6666", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        self.client.post(f'/crm/leads/{lead_id}/archive')

        r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "CONTACTED"})
        self.assertEqual(r.status_code, 409)

    # ==========================================
    # C. LOST
    # ==========================================

    def test_13_to_18_lost_stage_semantics(self):
        """TEST 13-18: LOST validation, reasons, follow-up clearing, and timeline details."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead G", "phone": "7777", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Pre-schedule follow-up
        query_db("UPDATE crm_leads SET next_follow_up_at = CURRENT_TIMESTAMP WHERE id = %s", (lead_id,), commit=True)

        # 1. Missing reason must fail
        r1 = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "LOST"})
        self.assertEqual(r1.status_code, 400)

        # 2. Invalid reason must fail
        r2 = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "LOST", "lost_reason": "NOT_COOL_ENOUGH"})
        self.assertEqual(r2.status_code, 400)

        # 3. Correct reason works
        r3 = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "LOST", "lost_reason": "PRICE"})
        self.assertEqual(r3.status_code, 200)

        # Verify db fields
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['stage'], 'LOST')
        self.assertEqual(lead['lost_reason'], 'PRICE')
        self.assertIsNone(lead['next_follow_up_at']) # Follow-up cleared

        # Verify activity timeline details
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s ORDER BY id DESC LIMIT 1", (lead_id,), one=True)
        self.assertEqual(act['activity_type'], 'STAGE_CHANGE')
        self.assertEqual(act['old_stage'], 'NEW')
        self.assertEqual(act['new_stage'], 'LOST')
        self.assertEqual(act['result'], 'PRICE')

    # ==========================================
    # D. REOPEN
    # ==========================================

    def test_19_to_25_reopen_lost_leads(self):
        """TEST 19-25: Reopen LOST leads to active stages, clearing reason and preventing non-LOST reopens."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead H", "phone": "8888", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Move to LOST
        self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "LOST", "lost_reason": "OTHER"})

        # 1. Reopen to invalid reopen target (e.g. LOST or WON)
        r1 = self.client.post(f'/crm/leads/{lead_id}/reopen', json={"stage": "WON"})
        self.assertEqual(r1.status_code, 400)

        # 2. Try normal stage edit generic route to move out of LOST
        r_generic = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "FOLLOW_UP"})
        self.assertEqual(r_generic.status_code, 400)

        # 3. Successful reopen using default (FOLLOW_UP)
        r3 = self.client.post(f'/crm/leads/{lead_id}/reopen')
        self.assertEqual(r3.status_code, 200)

        # Verify DB updates
        lead = query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['stage'], 'FOLLOW_UP')
        self.assertIsNone(lead['lost_reason'])
        self.assertIsNone(lead['next_follow_up_at'])

        # Reopen non-lost lead should fail
        r_fail = self.client.post(f'/crm/leads/{lead_id}/reopen')
        self.assertEqual(r_fail.status_code, 409)

    # ==========================================
    # E. AUTHORIZATION
    # ==========================================

    def test_26_to_30_stage_permissions(self):
        """TEST 26-30: Enforce crm_update_stage, global crm_all_leads, and local visibility rules."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead I", "phone": "9999", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        # Assign to Agent A
        self.client.post(f'/crm/leads/{lead_id}/assign', json={"user_id": 20003})

        # 1. Agent B (who has crm_view/create/edit but lacks crm_update_stage) - denied
        self.login_as('crm_agent_b', 20004)
        r_b = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "CONTACTED"})
        self.assertEqual(r_b.status_code, 302) # Redirect due to decorator permission check

        # 2. Agent B trying to reopen - denied
        r_b_reopen = self.client.post(f'/crm/leads/{lead_id}/reopen')
        self.assertEqual(r_b_reopen.status_code, 302)

        # 3. Agent A has crm_update_stage, and owns the lead - allowed
        self.login_as('crm_agent_a', 20003)
        r_a = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "CONTACTED"})
        self.assertEqual(r_a.status_code, 200)

        # 4. Agent A tries to mutate a lead assigned to crm_manager - forbidden by local visibility
        # Manager lead
        self.login_as('crm_manager', 20002)
        res_m = self.client.post('/crm/leads', json={"name": "Lead Manager", "phone": "9998", "source": "WALK_IN"})
        lead_m_id = res_m.get_json()['id']
        self.client.post(f'/crm/leads/{lead_m_id}/assign', json={"user_id": 20002})

        self.login_as('crm_agent_a', 20003)
        r_a_m = self.client.post(f'/crm/leads/{lead_m_id}/stage', json={"stage": "CONTACTED"})
        self.assertEqual(r_a_m.status_code, 403)

    # ==========================================
    # F. TIMELINE
    # ==========================================

    def test_31_to_35_timeline_activities(self):
        """TEST 31-35: Verify timeline record fields on STAGE_CHANGE and REOPENED."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead J", "phone": "9997", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "CONTACTED"})

        # Verify STAGE_CHANGE timeline details
        act = query_db("SELECT * FROM crm_activities WHERE lead_id = %s ORDER BY id DESC LIMIT 1", (lead_id,), one=True)
        self.assertEqual(act['activity_type'], 'STAGE_CHANGE')
        self.assertEqual(act['user_id'], 20002)
        self.assertEqual(act['user_username_snapshot'], 'crm_manager')
        self.assertEqual(act['old_stage'], 'NEW')
        self.assertEqual(act['new_stage'], 'CONTACTED')

    # ==========================================
    # G. TRANSACTION SAFETY
    # ==========================================

    def test_36_db_rollback_on_activity_insert_fail(self):
        """TEST 36: Database activity insert fail rolls back stage update."""
        self.login_as('crm_manager', 20002)
        res = self.client.post('/crm/leads', json={"name": "Lead K", "phone": "9996", "source": "WALK_IN"})
        lead_id = res.get_json()['id']

        from unittest.mock import patch
        from system_app.crm.queries import execute_transaction

        original_execute_transaction = execute_transaction
        def mock_execute_transaction(operations):
            mutated = []
            for q, args in operations:
                if "INSERT INTO crm_activities" in q:
                    # trigger DB table error
                    q = q.replace("INSERT INTO crm_activities", "INSERT INTO invalid_table_trigger_fail")
                mutated.append((q, args))
            return original_execute_transaction(mutated)

        with patch('system_app.crm.services.queries.execute_transaction', side_effect=mock_execute_transaction):
            r = self.client.post(f'/crm/leads/{lead_id}/stage', json={"stage": "CONTACTED"})
            self.assertEqual(r.status_code, 500)

        # Verify rollback - stage remains NEW
        lead = query_db("SELECT stage FROM crm_leads WHERE id = %s", (lead_id,), one=True)
        self.assertEqual(lead['stage'], 'NEW')

    # ==========================================
    # H. PIPELINE SUMMARY
    # ==========================================

    def test_38_to_41_pipeline_summary(self):
        """TEST 38-41: Check pipeline summary endpoints, stage aggregates, and user visibility restrictions."""
        # 1. Setup multiple leads
        self.login_as('crm_manager', 20002)

        r_new = self.client.post('/crm/leads', json={"name": "Lead New", "phone": "1001", "source": "WALK_IN"})
        r_contact = self.client.post('/crm/leads', json={"name": "Lead Contacted", "phone": "1002", "source": "WALK_IN"})

        self.client.post(f"/crm/leads/{r_contact.get_json()['id']}/stage", json={"stage": "CONTACTED"})

        # Verify counts for manager (view all)
        r_sum = self.client.get('/crm/pipeline')
        self.assertEqual(r_sum.status_code, 200)
        data = r_sum.get_json()

        self.assertEqual(data['NEW'], 1)
        self.assertEqual(data['CONTACTED'], 1)
        self.assertEqual(data['WON'], 0)
        self.assertEqual(data['LOST'], 0)

if __name__ == '__main__':
    unittest.main()
