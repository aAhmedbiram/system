from datetime import datetime, timedelta
from unittest.mock import patch
import unittest

from psycopg2.extras import Json

from system_app.app import app
from system_app.queries import query_db
from system_app.crm import queries, services
from system_app.crm.services import CAIRO_TZ, CRMConflictError, CRMForbiddenError, CRMNotFoundError


class _FakeDiag:
    def __init__(self, constraint_name):
        self.constraint_name = constraint_name


class _FakePgError(Exception):
    def __init__(self, pgcode, constraint_name):
        super().__init__("fake postgres error")
        self.pgcode = pgcode
        self.diag = _FakeDiag(constraint_name)


class TestCRMBulkPhaseB2(unittest.TestCase):
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
        query_db("DELETE FROM members WHERE name LIKE %s", ("PB2 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pb2_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',        'rino@test.com', 'pwd', TRUE, '{}'),
            (47001, 'pb2_exec',    'exec@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true}'),
            (47002, 'pb2_create',  'create@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (47003, 'pb2_none',    'none@test.com', 'pwd', TRUE, '{}'),
            (47011, 'pb2_user_a',  'a@test.com', 'pwd', TRUE, '{}'),
            (47012, 'pb2_user_b',  'b@test.com', 'pwd', TRUE, '{}'),
            (47013, 'pb2_user_c',  'c@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PB2 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pb2_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member_data(self, member_id, name, end_date='2099-01-01', phone=None, email=None):
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
            phone or f"07{member_id}",
            email or f"pb2{member_id}@example.com",
            None, None, None, None, None, end_date,
            None, None, 'VAL', 0, None, None
        ), commit=True)

    def _create_active_lead(self, lead_id, member_id, stage='NEW', archived=False):
        member = query_db("SELECT name, phone, email FROM members WHERE id = %s", (member_id,), one=True)
        query_db("""
            INSERT INTO crm_leads (
                id, member_id, name, phone, email, source, stage,
                created_by_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, %s, 'PB2_SOURCE', %s, %s, %s)
        """, (
            lead_id,
            member_id,
            member['name'],
            member['phone'],
            member['email'],
            stage,
            47001,
            archived,
        ), commit=True)

    def _preview(self, payload):
        return self.client.post('/crm/leads/bulk/preview', json=payload)

    def _execute(self, token):
        return self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})

    def _preview_equal(self, member_ids, user_ids):
        return self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "equal", "user_ids": user_ids},
            "source": "EXISTING_MEMBER"
        })

    def test_01_execute_creates_leads_and_assignment_fields(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1001, 1002, 1003, 1004, 1005]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Member {member_id}')

        preview = self._preview_equal(member_ids, [47013, 47012, 47011])
        self.assertEqual(preview.status_code, 200)
        token = preview.get_json()['preview_token']

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 5)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(data['failed'], 0)
        self.assertEqual([row['created'] for row in data['assignments']], [2, 2, 1])
        self.assertEqual([row['user_id'] for row in data['assignments']], [47011, 47012, 47013])

        leads = query_db(
            """
            SELECT member_id, name, phone, source, stage, assigned_user_id,
                   assigned_by_user_id, assigned_at, created_by_user_id
            FROM crm_leads
            WHERE member_id = ANY(%s)
            ORDER BY member_id ASC
            """,
            (member_ids,)
        ) or []
        self.assertEqual(len(leads), 5)
        for lead in leads:
            self.assertEqual(lead['source'], 'EXISTING_MEMBER')
            self.assertEqual(lead['stage'], 'NEW')
            self.assertEqual(lead['created_by_user_id'], 47001)
            self.assertIn(lead['member_id'], member_ids)

        created_by_member = {lead['member_id']: lead for lead in leads}
        self.assertEqual(created_by_member[1001]['assigned_user_id'], 47011)
        self.assertEqual(created_by_member[1002]['assigned_user_id'], 47011)
        self.assertEqual(created_by_member[1003]['assigned_user_id'], 47012)
        self.assertEqual(created_by_member[1004]['assigned_user_id'], 47012)
        self.assertEqual(created_by_member[1005]['assigned_user_id'], 47013)
        self.assertIsNotNone(created_by_member[1001]['assigned_by_user_id'])
        self.assertIsNotNone(created_by_member[1001]['assigned_at'])

        activity_count = query_db("SELECT COUNT(*) AS count FROM crm_activities", one=True)['count']
        self.assertEqual(activity_count, 0)

    def test_02_unassigned_execution_leaves_assignment_fields_null(self):
        self.login_as('pb2_create', 47002)
        member_ids = [1101, 1102]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Unassigned {member_id}')

        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = preview.get_json()['preview_token']

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        leads = query_db(
            """
            SELECT member_id, assigned_user_id, assigned_by_user_id, assigned_at
            FROM crm_leads
            WHERE member_id = ANY(%s)
            ORDER BY member_id ASC
            """,
            (member_ids,)
        ) or []
        self.assertEqual(len(leads), 2)
        for lead in leads:
            self.assertIsNone(lead['assigned_user_id'])
            self.assertIsNone(lead['assigned_by_user_id'])
            self.assertIsNone(lead['assigned_at'])

    def test_03_execution_uses_frozen_assignment_plan(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1201, 1202, 1203, 1204, 1205]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Frozen {member_id}')

        preview = self._preview_equal(member_ids, [47013, 47012, 47011])
        token = preview.get_json()['preview_token']

        operation = query_db(
            "SELECT snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        snapshot = operation['snapshot']
        snapshot['distribution']['user_ids'] = [47011]
        query_db(
            "UPDATE crm_bulk_lead_operations SET snapshot = %s WHERE token = %s",
            (Json(snapshot), token),
            commit=True
        )

        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual([row['user_id'] for row in data['assignments']], [47011, 47012, 47013])
        self.assertEqual([row['created'] for row in data['assignments']], [2, 2, 1])

    def test_04_member_missing_after_preview_is_skipped(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1301, 1302]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Missing {member_id}')

        token = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        query_db("DELETE FROM members WHERE id = %s", (1302,), commit=True)
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped_reasons']['member_missing'], 1)

    def test_05_active_lead_after_preview_is_skipped(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1401, 1402]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Active {member_id}')

        token = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        self._create_active_lead(91402, 1402, stage='NEW')
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 1)

    def test_06_invalid_assignee_after_preview_is_skipped(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1501, 1502, 1503]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Assignee {member_id}')

        preview = self._preview_equal(member_ids, [47011, 47012, 47013])
        token = preview.get_json()['preview_token']

        query_db("DELETE FROM users WHERE id = %s", (47012,), commit=True)
        result = self._execute(token)
        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 2)
        self.assertEqual(data['skipped_reasons']['invalid_employee'], 1)

    def test_07_execution_time_permission_revocation_blocks(self):
        self.login_as('pb2_exec', 47001)
        self._member_data(1601, 'PB2 Permission 1601')
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [1601]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = preview.get_json()['preview_token']

        query_db(
            "UPDATE users SET permissions = %s WHERE id = %s",
            (Json({"crm_view": True}), 47001),
            commit=True
        )
        result = self._execute(token)
        self.assertIn(result.status_code, [302, 403])

    def test_08_execution_time_assign_permission_revocation_blocks(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1701, 1702, 1703]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Assign Revoke {member_id}')

        token = self._preview_equal(member_ids, [47011, 47012, 47013]).get_json()['preview_token']
        query_db(
            "UPDATE users SET permissions = %s WHERE id = %s",
            (Json({"crm_view": True, "crm_create": True}), 47001),
            commit=True
        )
        result = self._execute(token)
        self.assertEqual(result.status_code, 403)

    def test_09_expired_token_and_wrong_owner_block_execution(self):
        self.login_as('pb2_exec', 47001)
        self._member_data(1801, 'PB2 Expired', '2099-01-01')
        token = self._preview({
            "selection": {"mode": "ids", "member_ids": [1801]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        self.assertEqual(self._execute(token).status_code, 404)

        self.login_as('pb2_create', 47002)
        self.assertEqual(self._execute(token).status_code, 403)

    def test_10_claim_idempotency_and_duplicate_safe_completion(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [1901, 1902]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Idempotent {member_id}')

        token = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        first = self._execute(token)
        self.assertEqual(first.status_code, 200)
        second = self._execute(token)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count'], 2)
        operation = query_db(
            "SELECT status, snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        self.assertEqual(operation['status'], 'COMPLETED')
        self.assertEqual(operation['snapshot']['execution']['created'], 2)

    def test_11_partial_unique_conflict_is_handled_as_skip(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [2001, 2002]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Unique {member_id}')

        token = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        original = queries.create_existing_member_lead_in_transaction

        def side_effect(cur, member_row, source, created_by_user_id, assigned_user_id=None):
            if member_row['id'] == 2002:
                raise _FakePgError('23505', 'idx_unique_active_member_lead')
            return original(cur, member_row, source, created_by_user_id, assigned_user_id)

        with patch('system_app.crm.queries.create_existing_member_lead_in_transaction', side_effect=side_effect):
            result = self._execute(token)

        self.assertEqual(result.status_code, 200)
        data = result.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 1)

    def test_12_operation_failure_keeps_prior_commits_and_marks_failed(self):
        self.login_as('pb2_exec', 47001)
        member_ids = [2101, 2102]
        for member_id in member_ids:
            self._member_data(member_id, f'PB2 Failure {member_id}')

        token = self._preview({
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        original = queries.create_existing_member_lead_in_transaction

        def fail_on_second(cur, member_row, source, created_by_user_id, assigned_user_id=None):
            if member_row['id'] == 2102:
                raise RuntimeError("boom")
            return original(cur, member_row, source, created_by_user_id, assigned_user_id)

        with patch('system_app.crm.queries.create_existing_member_lead_in_transaction', side_effect=fail_on_second):
            result = self._execute(token)
            self.assertEqual(result.status_code, 500)

        self.assertEqual(query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count'], 1)
        operation = query_db(
            "SELECT status, snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        self.assertEqual(operation['status'], 'FAILED')
        self.assertEqual(operation['snapshot']['execution']['failed'], 1)

    def test_13_500_member_plan_is_deterministic(self):
        eligible_member_ids = list(range(3001, 3501))
        assignable_users = [
            {"id": 47011, "username": "pb2_user_a"},
            {"id": 47012, "username": "pb2_user_b"},
            {"id": 47013, "username": "pb2_user_c"},
        ]
        assignment_plan = services._build_assignment_plan(eligible_member_ids, 'equal', assignable_users)
        self.assertEqual(len(assignment_plan), 500)
        self.assertEqual(len({row['member_id'] for row in assignment_plan}), 500)
        counts = {}
        for row in assignment_plan:
            counts[row['user_id']] = counts.get(row['user_id'], 0) + 1
        self.assertEqual(counts[47011], 167)
        self.assertEqual(counts[47012], 167)
        self.assertEqual(counts[47013], 166)

    def test_14_bulk_page_renders_preview_summary(self):
        self.login_as('pb2_exec', 47001)
        self._member_data(2201, 'PB2 Page Render', '2099-01-01')
        token = self._preview({
            "selection": {"mode": "ids", "member_ids": [2201]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).get_json()['preview_token']

        res = self.client.get('/crm/leads/bulk', query_string={'preview_token': token})
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Preview Ready', res.data)
        self.assertIn(b'Confirm &amp; Create Leads', res.data)


if __name__ == '__main__':
    unittest.main()
