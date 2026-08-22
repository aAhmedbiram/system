from datetime import datetime, timedelta
from unittest.mock import patch
import unittest

from psycopg2.extras import Json

from system_app.app import app
from system_app.crm import queries
from system_app.crm.services import CAIRO_TZ
from system_app.queries import query_db


class TestCRMBulkInvitationsPhase3(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get('TESTING')
        self._old_secret_key = app.config.get('SECRET_KEY')
        self._old_csrf_enabled = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE id BETWEEN %s AND %s", (79300, 79499), commit=True)
        query_db("DELETE FROM users WHERE id BETWEEN %s AND %s OR username LIKE %s", (59300, 59499, "p3_%"), commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (59301, 'p3_exec',  'exec@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true, "crm_bulk_leads": true}'),
            (59302, 'p3_create','create@test.com','pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_bulk_leads": true}'),
            (59303, 'p3_bulk',  'bulk@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_bulk_leads": true}'),
            (59304, 'p3_none',  'none@test.com',  'pwd', TRUE, '{}'),
            (59305, 'p3_super', 'super@test.com', 'pwd', TRUE, '{"super_admin": true}'),
            (59311, 'p3_user_a','a@test.com',     'pwd', TRUE, '{}'),
            (59312, 'p3_user_b','b@test.com',     'pwd', TRUE, '{}'),
            (59313, 'p3_user_c','c@test.com',     'pwd', TRUE, '{}')
        """, commit=True)
        self._member(79301, 'P3 Inviter', '01099999777')

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE id BETWEEN %s AND %s", (79300, 79499), commit=True)
        query_db("DELETE FROM users WHERE id BETWEEN %s AND %s OR username LIKE %s", (59300, 59499, "p3_%"), commit=True)
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member(self, member_id, name, phone, end_date='2099-01-01'):
        query_db("""
            INSERT INTO members (
                id, name, phone, email, age, gender, birthdate, actual_starting_date,
                starting_date, end_date, membership_packages, membership_fees,
                membership_status, invitations, comment, national_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            member_id,
            name,
            phone,
            f"p3{member_id}@example.com",
            None, None, None, None, None, end_date,
            'Gold', None, 'VAL', 0, None, None
        ), commit=True)

    def _invitation(self, invitation_id, friend_name, friend_phone, used_date,
                    used_by='p3_user', inviter_member_id=79301, inviter_name='P3 Inviter',
                    friend_email=None):
        query_db("""
            INSERT INTO invitations (
                id, member_id, member_name, friend_name, friend_phone, friend_email,
                used_date, used_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            invitation_id,
            inviter_member_id,
            inviter_name,
            friend_name,
            friend_phone,
            friend_email if friend_email is not None else f"{friend_name.lower().replace(' ', '')}@example.com",
            used_date,
            used_by
        ), commit=True)

    def _preview(self, selection, distribution, username='p3_exec', user_id=59301):
        self.login_as(username, user_id)
        return self.client.post('/crm/leads/bulk/preview', json={
            "selection": selection,
            "distribution": distribution,
            "source": "INVITATIONS"
        })

    def _execute(self, token):
        return self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})

    def _crm_lead_by_phone(self, phone):
        return query_db(
            "SELECT * FROM crm_leads WHERE TRIM(COALESCE(phone, '')) = %s ORDER BY id DESC LIMIT 1",
            (phone,),
            one=True
        )

    def test_01_execute_creates_invitation_lead_with_frozen_fields(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89301, 'Invitation Alpha', '01012345678', datetime(2026, 8, 1, 10, 0, 0), friend_email='alpha@test.com')
        before_invitations = query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count']

        preview = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345678"]},
            {"mode": "unassigned"}
        )
        self.assertEqual(preview.status_code, 200)
        token = preview.get_json()['preview_token']

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(data['failed'], 0)

        lead = self._crm_lead_by_phone('01012345678')
        self.assertIsNotNone(lead)
        self.assertIsNone(lead['member_id'])
        self.assertEqual(lead['source'], 'INVITATIONS')
        self.assertEqual(lead['stage'], 'NEW')
        self.assertEqual(lead['name'], 'Invitation Alpha')
        self.assertEqual(lead['phone'], '01012345678')
        self.assertEqual(lead['email'], 'alpha@test.com')
        self.assertIsNone(lead['assigned_user_id'])
        self.assertIsNone(lead['assigned_by_user_id'])
        self.assertIsNone(lead['assigned_at'])
        self.assertEqual(lead['created_by_user_id'], 59301)

        invitation = query_db(
            "SELECT id, member_id, member_name, friend_name, friend_phone, friend_email, used_date, used_by FROM invitations WHERE id = %s",
            (89301,),
            one=True
        )
        self.assertEqual(invitation['member_id'], 79301)
        self.assertEqual(invitation['member_name'], 'P3 Inviter')
        self.assertEqual(invitation['friend_name'], 'Invitation Alpha')
        self.assertEqual(invitation['friend_phone'], '01012345678')
        self.assertEqual(invitation['friend_email'], 'alpha@test.com')
        self.assertEqual(before_invitations, query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count'])

    def test_02_equal_distribution_uses_frozen_assignment_plan(self):
        self.login_as('p3_exec', 59301)
        for idx in range(1, 6):
            self._invitation(89310 + idx, f'Equal {idx}', f'0106666000{idx}', datetime(2026, 8, 2, 8, 0, 0))

        preview = self._preview(
            {"mode": "filters", "filters": {"search_name": "Equal"}},
            {"mode": "equal", "user_ids": [59313, 59312, 59311]}
        )
        self.assertEqual(preview.status_code, 200)
        preview_data = preview.get_json()
        self.assertEqual([row['lead_count'] for row in preview_data['distribution']], [2, 2, 1])

        token = preview_data['preview_token']
        snapshot = query_db(
            "SELECT snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )['snapshot']
        snapshot['distribution']['user_ids'] = [59311]
        query_db(
            "UPDATE crm_bulk_lead_operations SET snapshot = %s WHERE token = %s",
            (Json(snapshot), token),
            commit=True
        )

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual([row['user_id'] for row in data['assignments']], [59311, 59312, 59313])
        self.assertEqual([row['created'] for row in data['assignments']], [2, 2, 1])

        pattern = '0106666000%'
        leads = query_db(
            """
            SELECT phone, assigned_user_id
            FROM crm_leads
            WHERE TRIM(COALESCE(phone, '')) LIKE %s
            ORDER BY phone ASC
            """,
            (pattern,),
            one=False
        ) or []
        self.assertEqual(len(leads), 5)

    def test_03_mutated_invitation_row_does_not_change_frozen_execute_payload(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89321, 'Frozen Alpha', '01012345679', datetime(2026, 8, 3, 8, 0, 0), friend_email='frozen@test.com')
        preview = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345679"]},
            {"mode": "unassigned"}
        )
        token = preview.get_json()['preview_token']

        query_db(
            "UPDATE invitations SET friend_name = %s, friend_email = %s WHERE id = %s",
            ('Mutated Alpha', 'mutated@test.com', 89321),
            commit=True
        )

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        lead = self._crm_lead_by_phone('01012345679')
        self.assertEqual(lead['name'], 'Frozen Alpha')
        self.assertEqual(lead['email'], 'frozen@test.com')

    def test_04_member_now_exists_and_active_prospect_now_exists_are_skipped(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89331, 'Member Skip', '01012345670', datetime(2026, 8, 4, 8, 0, 0))
        self._invitation(89332, 'Lead Skip', '01012345671', datetime(2026, 8, 4, 9, 0, 0))
        token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345670", "01012345671"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']

        self._member(79331, 'P3 Member Skip', '01012345670')
        query_db(
            "INSERT INTO crm_leads (name, phone, source, stage, created_by_user_id) VALUES (%s, %s, 'WALK_IN', 'NEW', %s)",
            ('P3 Lead Skip', '01012345671', 59301),
            commit=True
        )
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['skipped_reasons']['member_now_exists'], 1)
        self.assertEqual(data['skipped_reasons']['crm_lead_now_exists'], 1)

    def test_05_terminal_and_archived_leads_do_not_block(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89341, 'Terminal Lead', '01012345672', datetime(2026, 8, 5, 8, 0, 0))
        self._invitation(89342, 'Archived Lead', '01012345673', datetime(2026, 8, 5, 9, 0, 0))
        token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345672", "01012345673"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']

        query_db(
            "INSERT INTO crm_leads (name, phone, source, stage, created_by_user_id) VALUES (%s, %s, 'WALK_IN', 'WON', %s)",
            ('P3 Won Lead', '01012345672', 59301),
            commit=True
        )
        query_db(
            "INSERT INTO crm_leads (name, phone, source, stage, created_by_user_id, is_archived) VALUES (%s, %s, 'WALK_IN', 'NEW', %s, TRUE)",
            ('P3 Archived Lead', '01012345673', 59301),
            commit=True
        )
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 2)
        lead_one = self._crm_lead_by_phone('01012345672')
        lead_two = self._crm_lead_by_phone('01012345673')
        self.assertEqual(lead_one['source'], 'INVITATIONS')
        self.assertEqual(lead_two['source'], 'INVITATIONS')

    def test_06_deleted_canonical_invitation_is_skipped(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89351, 'Missing Inv', '01012345674', datetime(2026, 8, 6, 8, 0, 0))
        token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345674"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']
        query_db("DELETE FROM invitations WHERE id = %s", (89351,), commit=True)
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 0)
        self.assertEqual(data['skipped_reasons']['invitation_missing'], 1)

    def test_07_invalid_employee_after_preview_and_permission_revocation(self):
        self.login_as('p3_exec', 59301)
        for idx in range(1, 4):
            self._invitation(89360 + idx, f'Employee {idx}', f'010123457{idx}0', datetime(2026, 8, 7, 8, idx, 0))

        preview = self._preview(
            {"mode": "filters", "filters": {"search_name": "Employee"}},
            {"mode": "equal", "user_ids": [59311, 59312, 59313]}
        )
        token = preview.get_json()['preview_token']
        permission_preview = self._preview(
            {"mode": "filters", "filters": {"search_name": "Employee"}},
            {"mode": "equal", "user_ids": [59311, 59312, 59313]}
        )
        permission_token = permission_preview.get_json()['preview_token']

        query_db("DELETE FROM users WHERE id = %s", (59312,), commit=True)
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.get_json()['skipped_reasons']['invalid_employee'], 1)

        query_db(
            "UPDATE users SET permissions = %s WHERE id = %s",
            (Json({"crm_view": True, "crm_create": True, "crm_bulk_leads": True}), 59301),
            commit=True
        )
        denied = self._execute(permission_token)
        self.assertEqual(denied.status_code, 403)

    def test_08_wrong_owner_expired_and_idempotent_execute(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89371, 'Owner Alpha', '01012345680', datetime(2026, 8, 8, 8, 0, 0))
        preview = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345680"]},
            {"mode": "unassigned"}
        )
        token = preview.get_json()['preview_token']

        self.login_as('p3_create', 59302)
        self.assertEqual(self._execute(token).status_code, 403)

        self.login_as('p3_exec', 59301)
        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        self.assertEqual(self._execute(token).status_code, 404)

        fresh = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345680"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']
        first = self._execute(fresh)
        second = self._execute(fresh)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(query_db("SELECT COUNT(*) AS count FROM crm_leads WHERE phone = %s", ('01012345680',), one=True)['count'], 1)

    def test_09_partial_failure_marks_failed_and_preserves_successful_candidates(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89381, 'Partial Alpha', '01012345681', datetime(2026, 8, 9, 9, 0, 0))
        self._invitation(89382, 'Partial Beta', '01012345682', datetime(2026, 8, 9, 8, 0, 0))
        token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345681", "01012345682"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']

        original = queries.create_invitation_lead_in_transaction

        def fail_on_second(cur, candidate_row, source, actor_id, target_user_id=None):
            if candidate_row.get('candidate_key') == '01012345682':
                raise RuntimeError("boom")
            return original(cur, candidate_row, source, actor_id, target_user_id)

        with patch('system_app.crm.queries.create_invitation_lead_in_transaction', side_effect=fail_on_second):
            result = self._execute(token)

        self.assertEqual(result.status_code, 500)
        self.assertEqual(query_db("SELECT COUNT(*) AS count FROM crm_leads WHERE phone IN (%s, %s)", ('01012345681', '01012345682'), one=True)['count'], 1)
        operation = query_db(
            "SELECT status, snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        self.assertEqual(operation['status'], 'FAILED')
        self.assertEqual(operation['snapshot']['execution']['failed'], 1)

    def test_10_existing_member_execution_path_remains_unchanged(self):
        self.login_as('p3_exec', 59301)
        self._member(79401, 'Existing Member', '01012345683')
        preview = self.client.post('/crm/leads/bulk/preview', json={
            "selection": {"mode": "ids", "member_ids": [79401]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(preview.status_code, 200)
        token = preview.get_json()['preview_token']
        result = self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})
        self.assertEqual(result.status_code, 200)
        lead = query_db("SELECT * FROM crm_leads WHERE member_id = %s", (79401,), one=True)
        self.assertIsNotNone(lead)
        self.assertEqual(lead['source'], 'EXISTING_MEMBER')
        self.assertEqual(lead['stage'], 'NEW')

    def test_11_successful_invitation_disappears_from_phase1_listing_and_is_visible_in_crm(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89391, 'List Alpha', '01012345684', datetime(2026, 8, 10, 8, 0, 0))
        token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345684"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']
        self._execute(token)

        listing = self.client.get('/crm/leads/bulk/invitations', query_string={'search_phone': '01012345684'})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual(listing.get_json()['total'], 0)

        leads = self.client.get('/crm/leads', query_string={'source': 'INVITATIONS', 'search': 'List Alpha'})
        self.assertEqual(leads.status_code, 200)
        self.assertEqual(leads.get_json()['total'], 1)

    def test_12_duplicate_phone_second_operation_skips_after_first_execute(self):
        self.login_as('p3_exec', 59301)
        self._invitation(89401, 'Dup Alpha', '01012345685', datetime(2026, 8, 11, 8, 0, 0))

        first_token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345685"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']
        second_token = self._preview(
            {"mode": "ids", "candidate_keys": ["01012345685"]},
            {"mode": "unassigned"}
        ).get_json()['preview_token']

        first = self._execute(first_token)
        second = self._execute(second_token)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()['skipped_reasons']['crm_lead_now_exists'], 1)
        self.assertEqual(query_db("SELECT COUNT(*) AS count FROM crm_leads WHERE phone = %s", ('01012345685',), one=True)['count'], 1)


if __name__ == '__main__':
    unittest.main()
