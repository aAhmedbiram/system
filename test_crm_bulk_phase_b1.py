from datetime import datetime, timedelta
import unittest

from psycopg2 import IntegrityError
from psycopg2.extras import Json

from system_app.app import app
from system_app.queries import query_db
from system_app.crm import services
from system_app.crm.services import CRMConflictError, CRMForbiddenError, CRMNotFoundError, CAIRO_TZ


class TestCRMBulkPhaseB1(unittest.TestCase):
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
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBB1 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbb1_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',      'rino@test.com', 'pwd', TRUE, '{}'),
            (46001, 'pbb1_create', 'create@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (46002, 'pbb1_assign', 'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true}'),
            (46005, 'pbb1_user_a', 'usera@test.com', 'pwd', TRUE, '{}'),
            (46011, 'pbb1_user_b', 'userb@test.com', 'pwd', TRUE, '{}'),
            (46003, 'pbb1_none', 'none@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBB1 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbb1_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member_data(self, member_id, name, end_date, phone=None, email=None):
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
            phone or f"02{member_id}",
            email or f"pbb1{member_id}@example.com",
            None, None, None, None, None, end_date,
            None, None, 'VAL', 0, None, None
        ), commit=True)

    def _preview(self, payload):
        return self.client.post('/crm/leads/bulk/preview', json=payload)

    def test_01_preview_creates_durable_db_operation(self):
        self.login_as('pbb1_create', 46001)
        self._member_data(9101, 'PBB1 Alpha', '2099-01-01')
        before_ops = query_db("SELECT COUNT(*) AS count FROM crm_bulk_lead_operations", one=True)['count']

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9101]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        after_ops = query_db("SELECT COUNT(*) AS count FROM crm_bulk_lead_operations", one=True)['count']
        self.assertEqual(after_ops, before_ops + 1)

    def test_02_snapshot_resolves_after_reload(self):
        self.login_as('pbb1_assign', 46002)
        for member_id in [9201, 9202, 9203, 9204, 9205]:
            self._member_data(member_id, f'PBB1 Member {member_id}', '2099-01-01')

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9201, 9202, 9203, 9204, 9205]},
            "distribution": {"mode": "equal", "user_ids": [46011, 46002, 46005]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        token = data['preview_token']

        # Verify the preview is durable in PostgreSQL rather than process-local memory.
        operation = query_db(
            """
            SELECT token, status, snapshot
            FROM crm_bulk_lead_operations
            WHERE token = %s
            """,
            (token,),
            one=True
        )
        self.assertIsNotNone(operation)
        self.assertEqual(operation['status'], 'PREVIEW')

        snapshot = services.get_bulk_preview_snapshot(
            token,
            {"id": 46002, "username": "pbb1_assign"}
        )
        self.assertEqual(
            snapshot['selection']['selected_member_ids'],
            [9201, 9202, 9203, 9204, 9205]
        )
        self.assertEqual(snapshot['assignment_plan'][0]['user_id'], 46002)

    def test_03_token_ownership_and_expiry(self):
        self.login_as('pbb1_assign', 46002)
        self._member_data(9301, 'PBB1 Token', '2099-01-01')
        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9301]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = res.get_json()['preview_token']

        with self.assertRaises(services.CRMForbiddenError):
            services.get_bulk_preview_snapshot(token, {"id": 46003, "username": "pbb1_none"})

        with self.assertRaises(services.CRMNotFoundError):
            services.get_bulk_preview_snapshot(token + 'tamper', {"id": 46002, "username": "pbb1_assign"})

        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        with self.assertRaises(services.CRMNotFoundError):
            services.get_bulk_preview_snapshot(token, {"id": 46002, "username": "pbb1_assign"})

        row = query_db(
            "SELECT token, status FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        self.assertIsNotNone(row)
        self.assertEqual(row['status'], 'PREVIEW')

    def test_04_assignment_plan_and_distribution_math(self):
        self.login_as('pbb1_assign', 46002)
        for member_id in [9401, 9402, 9403, 9404, 9405]:
            self._member_data(member_id, f'PBB1 Dist {member_id}', '2099-01-01')

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9401, 9402, 9403, 9404, 9405]},
            "distribution": {"mode": "equal", "user_ids": [46011, 46002, 46005]},
            "source": "EXISTING_MEMBER"
        })
        data = res.get_json()
        self.assertEqual([row['user_id'] for row in data['distribution']], [46002, 46005, 46011])
        self.assertEqual([row['lead_count'] for row in data['distribution']], [2, 2, 1])

        snapshot = services.get_bulk_preview_snapshot(data['preview_token'], {"id": 46002, "username": "pbb1_assign"})
        self.assertEqual(
            snapshot['assignment_plan'],
            [
                {"member_id": 9401, "user_id": 46002},
                {"member_id": 9402, "user_id": 46002},
                {"member_id": 9403, "user_id": 46005},
                {"member_id": 9404, "user_id": 46005},
                {"member_id": 9405, "user_id": 46011},
            ]
        )

    def test_05_unassigned_preview_uses_null_user_ids(self):
        self.login_as('pbb1_create', 46001)
        self._member_data(9501, 'PBB1 Unassigned 1', '2099-01-01')
        self._member_data(9502, 'PBB1 Unassigned 2', '2099-01-01')

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9501, 9502]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        snapshot = services.get_bulk_preview_snapshot(
            res.get_json()['preview_token'],
            {"id": 46001, "username": "pbb1_create"}
        )
        self.assertEqual(snapshot['assignment_plan'], [
            {"member_id": 9501, "user_id": None},
            {"member_id": 9502, "user_id": None},
        ])
        self.assertEqual(snapshot['distribution']['mode'], 'unassigned')

    def test_06_duplicate_token_is_rejected(self):
        token = "duplicate-token"
        expires_at = datetime.now(CAIRO_TZ) + timedelta(minutes=15)
        inserted_id = query_db(
            """
            INSERT INTO crm_bulk_lead_operations (
                token, created_by_user_id, status, snapshot, created_at, expires_at
            ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
            RETURNING id
            """,
            (token, 46001, 'PREVIEW', Json({"hello": "world"}), expires_at),
            one=True,
            commit=True
        )['id']
        self.assertTrue(inserted_id)
        with self.assertRaises(ValueError):
            query_db(
                """
                INSERT INTO crm_bulk_lead_operations (
                    token, created_by_user_id, status, snapshot, created_at, expires_at
                ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
                """,
                (token, 46001, 'PREVIEW', Json({"hello": "world"}), expires_at),
                commit=True
            )

    def test_07_preview_no_lead_or_activity_side_effects(self):
        self.login_as('pbb1_create', 46001)
        self._member_data(9601, 'PBB1 Side Effect', '2099-01-01')

        before_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']
        before_activities = query_db("SELECT COUNT(*) AS count FROM crm_activities", one=True)['count']

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9601]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)

        after_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']
        after_activities = query_db("SELECT COUNT(*) AS count FROM crm_activities", one=True)['count']
        self.assertEqual(before_leads, after_leads)
        self.assertEqual(before_activities, after_activities)

    def test_08_atomic_claim_helper(self):
        self.login_as('pbb1_assign', 46002)
        self._member_data(9701, 'PBB1 Claim', '2099-01-01')
        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [9701]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = res.get_json()['preview_token']

        claimed = services.claim_bulk_preview_operation(
            token,
            {"id": 46002, "username": "pbb1_assign"}
        )
        self.assertIsNotNone(claimed)
        self.assertEqual(claimed['status'], 'EXECUTING')

        with self.assertRaises(services.CRMConflictError):
            services.claim_bulk_preview_operation(
                token,
                {"id": 46002, "username": "pbb1_assign"}
            )


if __name__ == '__main__':
    unittest.main()
