"""Isolated PostgreSQL verification for combined private-training invitations.

This module intentionally requires TEST_DATABASE_URL. It never reads
DATABASE_URL and is skipped when the explicit isolated URL is absent.
"""

import hashlib
import os
import pathlib
import threading
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from unittest.mock import patch

import psycopg2
from psycopg2.extras import Json

TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")


@unittest.skipUnless(TEST_DATABASE_URL, "TEST_DATABASE_URL is not set")
class PrivateTrainingInvitationPostgresTests(unittest.TestCase):
    user_id = 981001
    other_user_id = 981002
    member_id = 982001

    @classmethod
    def setUpClass(cls):
        # The application has historically read DATABASE_URL/PGURL. This test
        # supplies only TEST_DATABASE_URL and patches the already-imported
        # module constant; no DATABASE_URL fallback is possible here.
        import system_app.app  # noqa: F401
        import system_app.queries as app_queries
        from system_app.private_training.queries import ensure_private_training_tables

        cls.app_queries = app_queries
        cls.app_queries.DATABASE_URL = TEST_DATABASE_URL
        cls.app_queries._connection_pool = None
        app_queries.create_table()
        ensure_private_training_tables()
        cls.migration_sql = pathlib.Path(__file__).parent / "system_app/migrations/add_private_training_checkin_invitations.sql"
        cls.apply_migration()
        cls.apply_migration()  # repeatability check

    @classmethod
    def apply_migration(cls):
        with psycopg2.connect(TEST_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute(cls.migration_sql.read_text())

    @classmethod
    def tearDownClass(cls):
        with psycopg2.connect(TEST_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM private_training_checkin_operations WHERE user_id IN (%s, %s)", (cls.user_id, cls.other_user_id))
                cur.execute("DELETE FROM private_training_portal_tokens WHERE created_by_user_id IN (%s, %s)", (cls.user_id, cls.other_user_id))
                cur.execute("DELETE FROM private_training_sessions WHERE trainer_user_id IN (%s, %s)", (cls.user_id, cls.other_user_id))
                cur.execute("DELETE FROM private_training_subscriptions WHERE trainer_user_id IN (%s, %s)", (cls.user_id, cls.other_user_id))
                cur.execute("DELETE FROM members WHERE id = %s", (cls.member_id,))

    def setUp(self):
        from system_app.queries import query_db
        from system_app.func import get_cairo_date

        self.query_db = query_db
        self.today = get_cairo_date()
        self.query_db(
            """INSERT INTO users (id, username, email, password, is_approved, permissions)
               VALUES (%s, %s, %s, 'test', TRUE, %s)
               ON CONFLICT (id) DO UPDATE SET permissions = EXCLUDED.permissions, is_approved = TRUE""",
            (self.user_id, "Hossam", "pg_pt_trainer@test.local", Json({"private_training_trainer": True})), commit=True,
        )
        self.query_db(
            """INSERT INTO users (id, username, email, password, is_approved, permissions)
               VALUES (%s, %s, %s, 'test', TRUE, %s)
               ON CONFLICT (id) DO UPDATE SET permissions = EXCLUDED.permissions, is_approved = TRUE""",
            (self.other_user_id, "Rino", "pg_pt_other@test.local", Json({"private_training_trainer": True})), commit=True,
        )
        self.query_db(
            """INSERT INTO members (id, name, phone, membership_status, starting_date, end_date)
               VALUES (%s, 'PG WhatsApp Member', '01012345678', 'ACTIVE', %s, %s)
               ON CONFLICT (id) DO UPDATE SET phone = EXCLUDED.phone""",
            (self.member_id, self.today - timedelta(days=1), self.today + timedelta(days=30)), commit=True,
        )
        self.subscription_id = self.query_db(
            """INSERT INTO private_training_subscriptions
               (member_id, client_type, client_name, client_phone, trainer_user_id, total_sessions, private_start_date, private_expiry_date, status)
               VALUES (%s, 'MEMBER', 'PG WhatsApp Member', '01012345678', %s, 3, %s, %s, 'ACTIVE') RETURNING id""",
            (self.member_id, self.user_id, self.today - timedelta(days=1), self.today + timedelta(days=30)), one=True, commit=True,
        )["id"]
        self.user = {"id": self.user_id, "username": "Hossam", "is_approved": True, "permissions": {"private_training_trainer": True}}
        self.other_user = {"id": self.other_user_id, "username": "Rino", "is_approved": True, "permissions": {"private_training_trainer": True}}

    def tearDown(self):
        with psycopg2.connect(TEST_DATABASE_URL) as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM private_training_checkin_operations WHERE subscription_id = %s", (self.subscription_id,))
                cur.execute("DELETE FROM private_training_portal_tokens WHERE subscription_id = %s", (self.subscription_id,))
                cur.execute("DELETE FROM private_training_sessions WHERE subscription_id = %s", (self.subscription_id,))
                cur.execute("DELETE FROM private_training_subscriptions WHERE id = %s", (self.subscription_id,))

    def create(self, user=None, operation=None, workout="Leg Day", key="s" * 32):
        from system_app.private_training.services import create_private_training_checkin_invitation
        return create_private_training_checkin_invitation(user or self.user, self.subscription_id, workout, operation or uuid.uuid4(), key)

    def test_success_replay_and_persisted_secrets(self):
        from system_app.private_training.services import _deterministic_portal_token
        operation = uuid.uuid4()
        first = self.create(operation=operation)
        second = self.create(operation=operation)
        self.assertFalse(first["replayed"])
        self.assertEqual(first["session"]["trainer_display_name"], "Hossam")
        self.assertTrue(second["replayed"])
        self.assertEqual(first["session"]["id"], second["session"]["id"])
        self.assertEqual(first["raw_token"], second["raw_token"])
        token_hash = self.query_db("SELECT token_hash FROM private_training_portal_tokens WHERE session_id = %s", (first["session"]["id"],), one=True)["token_hash"].strip()
        self.assertEqual(token_hash, hashlib.sha256(_deterministic_portal_token("s" * 32, operation, self.user_id, self.subscription_id, first["session"]["id"]).encode()).hexdigest())
        row = self.query_db("SELECT * FROM private_training_checkin_operations WHERE client_operation_id = %s", (str(operation),), one=True)
        self.assertEqual(row["status"], "COMPLETED")
        self.assertNotIn("raw_token", row)
        self.assertNotIn("wa.me", str(row))
        self.assertEqual(self.query_db("SELECT COUNT(*) AS n FROM private_training_sessions WHERE subscription_id = %s", (self.subscription_id,), one=True)["n"], 1)
        self.assertEqual(self.query_db("SELECT COUNT(*) AS n FROM private_training_portal_tokens WHERE subscription_id = %s AND revoked_at IS NULL", (self.subscription_id,), one=True)["n"], 1)

    def test_same_uuid_concurrency_and_cross_user_replay(self):
        operation = uuid.uuid4()
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: self.create(operation=operation), range(2)))
        self.assertEqual({result["session"]["id"] for result in results}, {results[0]["session"]["id"]})
        with self.assertRaises(Exception):
            self.create(user=self.other_user, operation=operation)

    def test_different_uuid_respects_pending_rule(self):
        self.create()
        from system_app.private_training.services import PrivateTrainingPendingSessionConflictError
        with self.assertRaises(PrivateTrainingPendingSessionConflictError):
            self.create(operation=uuid.uuid4(), workout="Another")

    def test_invalid_phone_and_weak_key_create_nothing(self):
        self.query_db("UPDATE private_training_subscriptions SET client_phone = '' WHERE id = %s", (self.subscription_id,), commit=True)
        from system_app.private_training.services import PrivateTrainingPhoneError, PrivateTrainingFeatureUnavailableError
        with self.assertRaises(PrivateTrainingPhoneError):
            self.create()
        self.query_db("UPDATE private_training_subscriptions SET client_phone = '01012345678' WHERE id = %s", (self.subscription_id,), commit=True)
        with self.assertRaises(PrivateTrainingFeatureUnavailableError):
            self.create(key="weak")
        self.assertEqual(self.query_db("SELECT COUNT(*) AS n FROM private_training_sessions WHERE subscription_id = %s", (self.subscription_id,), one=True)["n"], 0)

    def test_revocation_rolls_back_when_token_insert_fails(self):
        from system_app.private_training.services import _deterministic_portal_token, generate_portal_token
        old = generate_portal_token(self.user, self.subscription_id)
        with patch("system_app.private_training.services._deterministic_portal_token", return_value=old["raw_token"]):
            with self.assertRaises(psycopg2.IntegrityError):
                self.create()
        self.assertIsNotNone(self.query_db("SELECT id FROM private_training_portal_tokens WHERE token_hash = %s AND revoked_at IS NULL", (old["token"]["token_hash"],), one=True))
        self.assertEqual(self.query_db("SELECT COUNT(*) AS n FROM private_training_sessions WHERE subscription_id = %s", (self.subscription_id,), one=True)["n"], 0)

    def test_session_bound_token_approval_and_legacy_compatibility(self):
        from system_app.private_training.services import approve_private_training_session, resolve_portal_token, create_private_training_session_checkin
        result = self.create()
        context = resolve_portal_token(result["raw_token"])
        approved = approve_private_training_session(self.subscription_id, result["session"]["id"], {"subscription_id": self.subscription_id, "session_id": result["session"]["id"]})
        self.assertEqual(approved["session"]["status"], "APPROVED")
        legacy = generate_legacy = __import__("system_app.private_training.services", fromlist=["generate_portal_token"]).generate_portal_token(self.user, self.subscription_id)
        second = create_private_training_session_checkin(self.user, self.subscription_id, "Second")
        # The session-bound token cannot authorize the later session.
        with self.assertRaises(Exception):
            approve_private_training_session(self.subscription_id, second["id"], {"subscription_id": self.subscription_id, "session_id": result["session"]["id"]})
        self.assertIsNotNone(resolve_portal_token(legacy["raw_token"]))


if __name__ == "__main__":
    unittest.main()
