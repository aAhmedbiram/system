import threading
import unittest
from datetime import timedelta

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.private_training.permissions import (
    PRIVATE_TRAINING_MANAGE,
    PRIVATE_TRAINING_TRAINER,
    PRIVATE_TRAINING_VIEW,
)
from system_app.private_training.services import (
    PrivateTrainingAlreadyProcessedError,
    PrivateTrainingCancelledError,
    PrivateTrainingCompletedError,
    PrivateTrainingConflictError,
    PrivateTrainingExpiredError,
    PrivateTrainingForbiddenError,
    PrivateTrainingInvalidTrainerError,
    PrivateTrainingNotFoundError,
    PrivateTrainingPendingSessionConflictError,
    PrivateTrainingSubscriptionConflictError,
    create_private_training_session_checkin,
    create_private_training_subscription,
    current_private_training_counts,
    generate_portal_token,
    list_private_clients_for_trainer,
    remaining_sessions,
    reject_private_training_session,
    resolve_portal_token,
    revoke_portal_token,
    approve_private_training_session,
    get_subscription_effective_status,
    get_private_training_subscription,
)


class PrivateTrainingPhase1ATest(unittest.TestCase):
    manager_user_id = 910001
    trainer_a_user_id = 910002
    trainer_b_user_id = 910003
    viewer_user_id = 910004
    member_a_id = 920001
    member_b_id = 920002
    member_c_id = 920003
    member_d_id = 920004
    member_e_id = 920005

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False

        self._cleanup_private_training()
        self._upsert_users()
        self._upsert_members()

        self.manager_user = self._load_user(self.manager_user_id)
        self.trainer_a_user = self._load_user(self.trainer_a_user_id)
        self.trainer_b_user = self._load_user(self.trainer_b_user_id)
        self.viewer_user = self._load_user(self.viewer_user_id)

    def tearDown(self):
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()

    def _today(self):
        return get_cairo_date()

    def _date_str(self, delta_days):
        return (self._today() + timedelta(days=delta_days)).strftime("%Y-%m-%d")

    def _upsert_users(self):
        users = [
            (self.manager_user_id, "pt_manager", "pt_manager@test.local", {"private_training_manage": True}),
            (self.trainer_a_user_id, "pt_trainer_a", "pt_trainer_a@test.local", {"private_training_trainer": True}),
            (self.trainer_b_user_id, "pt_trainer_b", "pt_trainer_b@test.local", {"private_training_trainer": True}),
            (self.viewer_user_id, "pt_viewer", "pt_viewer@test.local", {"private_training_view": True}),
        ]
        for user_id, username, email, permissions in users:
            query_db(
                """
                INSERT INTO users (id, username, email, password, is_approved, permissions)
                VALUES (%s, %s, %s, %s, TRUE, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    password = EXCLUDED.password,
                    is_approved = EXCLUDED.is_approved,
                    permissions = EXCLUDED.permissions
                """,
                (user_id, username, email, "pwd", Json(permissions)),
                commit=True,
            )

    def _upsert_members(self):
        members = [
            (self.member_a_id, "PT Member A", "700001", self._date_str(-1), self._date_str(30)),
            (self.member_b_id, "PT Member B", "700002", self._date_str(-1), self._date_str(30)),
            (self.member_c_id, "PT Member C", "700003", self._date_str(-1), self._date_str(30)),
            (self.member_d_id, "PT Member D", "700004", self._date_str(-1), self._date_str(30)),
            (self.member_e_id, "PT Member E", "700005", self._date_str(-1), self._date_str(30)),
        ]
        for member_id, name, phone, start_date, end_date in members:
            query_db(
                """
                INSERT INTO members (
                    id, name, phone, membership_packages, membership_fees,
                    membership_status, starting_date, end_date
                ) VALUES (%s, %s, %s, '1 Month', 500.0, 'VAL', %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    phone = EXCLUDED.phone,
                    membership_packages = EXCLUDED.membership_packages,
                    membership_fees = EXCLUDED.membership_fees,
                    membership_status = EXCLUDED.membership_status,
                    starting_date = EXCLUDED.starting_date,
                    end_date = EXCLUDED.end_date
                """,
                (member_id, name, phone, start_date, end_date),
                commit=True,
            )

    def _cleanup_private_training(self):
        query_db(
            """
            DELETE FROM private_training_portal_tokens
            WHERE subscription_id IN (
                SELECT id FROM private_training_subscriptions
                WHERE member_id BETWEEN 920001 AND 920005
                   OR trainer_user_id BETWEEN 910001 AND 910004
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_sessions
            WHERE subscription_id IN (
                SELECT id FROM private_training_subscriptions
                WHERE member_id BETWEEN 920001 AND 920005
                   OR trainer_user_id BETWEEN 910001 AND 910004
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE member_id BETWEEN 920001 AND 920005
               OR trainer_user_id BETWEEN 910001 AND 910004
            """,
            commit=True,
        )

    def _cleanup_members(self):
        query_db(
            "DELETE FROM members WHERE id BETWEEN 920001 AND 920005",
            commit=True,
        )

    def _cleanup_users(self):
        query_db(
            "DELETE FROM users WHERE id BETWEEN 910001 AND 910004",
            commit=True,
        )

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_subscription(self, member_id, trainer_user_id, total_sessions, start_offset_days, expiry_offset_days, creator=None):
        creator = creator or self.manager_user
        return create_private_training_subscription(
            creator,
            member_id,
            trainer_user_id,
            total_sessions,
            self._date_str(start_offset_days),
            self._date_str(expiry_offset_days),
        )["subscription"]

    def _make_active_subscription(self, member_id, trainer_user_id=None, total_sessions=2):
        trainer_user_id = trainer_user_id or self.trainer_a_user_id
        return self._create_subscription(member_id, trainer_user_id, total_sessions, 0, 30)

    def _make_future_subscription(self, member_id, trainer_user_id=None, total_sessions=2):
        trainer_user_id = trainer_user_id or self.trainer_a_user_id
        return self._create_subscription(member_id, trainer_user_id, total_sessions, 2, 30)

    def _check_in(self, subscription_id, trainer_user=None):
        trainer_user = trainer_user or self.trainer_a_user
        return create_private_training_session_checkin(trainer_user, subscription_id)

    def _approve(self, subscription_id, session_id):
        return approve_private_training_session(
            subscription_id,
            session_id,
            {"subscription_id": subscription_id},
        )

    def _reject(self, subscription_id, session_id, reason):
        return reject_private_training_session(
            subscription_id,
            session_id,
            reason,
            {"subscription_id": subscription_id},
        )

    def _expire_subscription(self, subscription_id):
        query_db(
            """
            UPDATE private_training_subscriptions
            SET private_start_date = %s,
                private_expiry_date = %s
            WHERE id = %s
            """,
            (self._date_str(-2), self._date_str(-1), subscription_id),
            commit=True,
        )

    def test_01_authorized_manager_creates_subscription(self):
        result = create_private_training_subscription(
            self.manager_user,
            self.member_a_id,
            self.trainer_a_user_id,
            3,
            self._date_str(1),
            self._date_str(30),
        )
        subscription = result["subscription"]
        self.assertEqual(subscription["member_id"], self.member_a_id)
        self.assertEqual(subscription["trainer_user_id"], self.trainer_a_user_id)
        self.assertEqual(subscription["created_by_user_id"], self.manager_user_id)
        self.assertEqual(subscription["total_sessions"], 3)
        self.assertEqual(subscription["effective_status"], "ASSIGNED")

    def test_02_unauthorized_user_cannot_create(self):
        with self.assertRaises(PrivateTrainingForbiddenError):
            create_private_training_subscription(
                self.viewer_user,
                self.member_a_id,
                self.trainer_a_user_id,
                3,
                self._date_str(1),
                self._date_str(30),
            )

    def test_03_invalid_member_rejected(self):
        with self.assertRaises(PrivateTrainingNotFoundError):
            create_private_training_subscription(
                self.manager_user,
                999999,
                self.trainer_a_user_id,
                3,
                self._date_str(1),
                self._date_str(30),
            )

    def test_04_invalid_trainer_rejected(self):
        with self.assertRaises(PrivateTrainingInvalidTrainerError):
            create_private_training_subscription(
                self.manager_user,
                self.member_a_id,
                999998,
                3,
                self._date_str(1),
                self._date_str(30),
            )

    def test_05_trainer_without_trainer_permission_rejected(self):
        query_db(
            """
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (910005, 'pt_no_trainer_perm', 'pt_no_trainer_perm@test.local', 'pwd', TRUE, '{"private_training_view": true}')
            ON CONFLICT (id) DO UPDATE SET permissions = EXCLUDED.permissions
            """,
            commit=True,
        )
        with self.assertRaises(PrivateTrainingInvalidTrainerError):
            create_private_training_subscription(
                self.manager_user,
                self.member_a_id,
                910005,
                3,
                self._date_str(1),
                self._date_str(30),
            )
        query_db("DELETE FROM users WHERE id = 910005", commit=True)

    def test_06_total_sessions_must_be_positive(self):
        with self.assertRaises(ValueError):
            create_private_training_subscription(
                self.manager_user,
                self.member_a_id,
                self.trainer_a_user_id,
                0,
                self._date_str(1),
                self._date_str(30),
            )

    def test_07_expiry_before_start_rejected(self):
        with self.assertRaises(ValueError):
            create_private_training_subscription(
                self.manager_user,
                self.member_a_id,
                self.trainer_a_user_id,
                2,
                self._date_str(10),
                self._date_str(5),
            )

    def test_08_future_start_subscription_is_assigned(self):
        subscription = self._make_future_subscription(self.member_a_id)
        self.assertEqual(subscription["status"], "ASSIGNED")
        self.assertEqual(get_subscription_effective_status(subscription), "ASSIGNED")

    def test_09_current_start_subscription_is_active(self):
        subscription = self._make_active_subscription(self.member_a_id)
        self.assertEqual(subscription["status"], "ACTIVE")
        self.assertEqual(get_subscription_effective_status(subscription), "ACTIVE")

    def test_10_already_expired_creation_rejected(self):
        with self.assertRaises(PrivateTrainingExpiredError):
            create_private_training_subscription(
                self.manager_user,
                self.member_a_id,
                self.trainer_a_user_id,
                2,
                self._date_str(-10),
                self._date_str(-1),
            )

    def test_11_creator_sales_user_retained(self):
        subscription = self._make_active_subscription(self.member_a_id)
        self.assertEqual(subscription["created_by_user_id"], self.manager_user_id)

    def test_12_one_effective_active_subscription_per_member(self):
        first = self._make_active_subscription(self.member_b_id)
        with self.assertRaises(PrivateTrainingSubscriptionConflictError):
            create_private_training_subscription(
                self.manager_user,
                self.member_b_id,
                self.trainer_a_user_id,
                2,
                self._date_str(1),
                self._date_str(30),
            )
        self.assertEqual(get_subscription_effective_status(first), "ACTIVE")

    def test_13_completed_historical_subscription_does_not_block_new_subscription(self):
        subscription = self._create_subscription(self.member_c_id, self.trainer_a_user_id, 1, 0, 30)
        session_row = self._check_in(subscription["id"])
        self._approve(subscription["id"], session_row["id"])
        refreshed = get_private_training_subscription(subscription["id"])
        self.assertEqual(refreshed["effective_status"], "COMPLETED")

        new_subscription = create_private_training_subscription(
            self.manager_user,
            self.member_c_id,
            self.trainer_a_user_id,
            2,
            self._date_str(1),
            self._date_str(30),
        )["subscription"]
        self.assertIn(new_subscription["status"], ("ASSIGNED", "ACTIVE"))

    def test_14_expired_historical_subscription_does_not_block_new_subscription(self):
        subscription = self._make_active_subscription(self.member_d_id)
        self._expire_subscription(subscription["id"])
        expired = get_private_training_subscription(subscription["id"])
        self.assertEqual(expired["effective_status"], "EXPIRED")

        new_subscription = create_private_training_subscription(
            self.manager_user,
            self.member_d_id,
            self.trainer_a_user_id,
            2,
            self._date_str(1),
            self._date_str(30),
        )["subscription"]
        self.assertIn(new_subscription["status"], ("ASSIGNED", "ACTIVE"))

    def test_15_approved_count_derives_correctly(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._check_in(subscription["id"])
        pending = query_db(
            "SELECT * FROM private_training_sessions WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL' ORDER BY id DESC LIMIT 1",
            (subscription["id"],),
            one=True,
        )
        self.assertEqual(current_private_training_counts(subscription["id"])["approved_count"], 0)
        self._approve(subscription["id"], pending["id"])
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 1)
        self.assertEqual(counts["remaining_sessions"], 1)

    def test_16_pending_does_not_consume_quota(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._check_in(subscription["id"])
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 0)
        self.assertEqual(counts["remaining_sessions"], 2)

    def test_17_rejected_does_not_consume_quota(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._check_in(subscription["id"])
        pending = query_db(
            "SELECT * FROM private_training_sessions WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL' ORDER BY id DESC LIMIT 1",
            (subscription["id"],),
            one=True,
        )
        self._reject(subscription["id"], pending["id"], "Member requested a different time")
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 0)
        self.assertEqual(counts["remaining_sessions"], 2)

    def test_18_approved_consumes_exactly_one(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._check_in(subscription["id"])
        pending = query_db(
            "SELECT * FROM private_training_sessions WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL' ORDER BY id DESC LIMIT 1",
            (subscription["id"],),
            one=True,
        )
        self._approve(subscription["id"], pending["id"])
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 1)
        self.assertEqual(counts["remaining_sessions"], 1)

    def test_19_trainer_can_list_only_own_subscriptions(self):
        own = self._make_active_subscription(self.member_a_id, trainer_user_id=self.trainer_a_user_id)
        other = self._make_active_subscription(self.member_b_id, trainer_user_id=self.trainer_b_user_id)
        own_rows = list_private_clients_for_trainer(self.trainer_a_user)
        trainer_a_ids = {row["id"] for row in own_rows}
        self.assertIn(own["id"], trainer_a_ids)
        self.assertNotIn(other["id"], trainer_a_ids)

    def test_20_trainer_cannot_open_another_trainers_subscription(self):
        other = self._make_active_subscription(self.member_b_id, trainer_user_id=self.trainer_b_user_id)
        with self.assertRaises(PrivateTrainingForbiddenError):
            create_private_training_session_checkin(self.trainer_a_user, other["id"])

    def test_21_session_checkin_creates_pending(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        self.assertEqual(session_row["status"], "PENDING_MEMBER_APPROVAL")
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 0)

    def test_22_second_checkin_blocked_while_pending_exists(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._check_in(subscription["id"])
        with self.assertRaises(PrivateTrainingPendingSessionConflictError):
            self._check_in(subscription["id"])

    def test_23_pending_unique_index_and_lock_prevent_double_checkin(self):
        subscription = self._make_active_subscription(self.member_b_id, total_sessions=2)
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def worker():
            try:
                barrier.wait()
                result = self._check_in(subscription["id"])
                outcomes.append(result["id"])
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        pending_rows = query_db(
            "SELECT * FROM private_training_sessions WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL'",
            (subscription["id"],),
        ) or []
        self.assertEqual(len(pending_rows), 1)
        self.assertEqual(len(outcomes), 1)
        self.assertEqual(len(errors), 1)
        self.assertIsInstance(errors[0], PrivateTrainingPendingSessionConflictError)

    def test_24_approve_pending_marks_approved(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        result = self._approve(subscription["id"], session_row["id"])
        self.assertEqual(result["session"]["status"], "APPROVED")
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 1)

    def test_25_repeated_approve_is_idempotent(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        first = self._approve(subscription["id"], session_row["id"])
        second = self._approve(subscription["id"], session_row["id"])
        self.assertEqual(first["session"]["status"], "APPROVED")
        self.assertEqual(second["outcome"], "already_approved")
        self.assertEqual(current_private_training_counts(subscription["id"])["approved_count"], 1)

    def test_26_reject_requires_reason(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        with self.assertRaises(ValueError):
            self._reject(subscription["id"], session_row["id"], "")

    def test_27_reject_marks_rejected_and_consumes_nothing(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        result = self._reject(subscription["id"], session_row["id"], "Member asked to postpone")
        self.assertEqual(result["session"]["status"], "REJECTED")
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 0)
        self.assertEqual(counts["remaining_sessions"], 2)

    def test_28_after_rejection_new_checkin_can_be_created(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        session_row = self._check_in(subscription["id"])
        self._reject(subscription["id"], session_row["id"], "Member asked to postpone")
        new_session = self._check_in(subscription["id"])
        self.assertEqual(new_session["status"], "PENDING_MEMBER_APPROVAL")

    def test_29_final_approved_session_completes_subscription(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, 1, 0, 30)
        session_row = self._check_in(subscription["id"])
        result = self._approve(subscription["id"], session_row["id"])
        self.assertEqual(result["new_subscription_status"], "COMPLETED")
        refreshed = get_private_training_subscription(subscription["id"])
        self.assertEqual(refreshed["effective_status"], "COMPLETED")

    def test_30_completed_subscription_blocks_new_checkin(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, 1, 0, 30)
        session_row = self._check_in(subscription["id"])
        self._approve(subscription["id"], session_row["id"])
        with self.assertRaises(PrivateTrainingCompletedError):
            self._check_in(subscription["id"])

    def test_31_expired_subscription_blocks_new_checkin(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._expire_subscription(subscription["id"])
        with self.assertRaises(PrivateTrainingExpiredError):
            self._check_in(subscription["id"])

    def test_32_cancelled_subscription_blocks_new_checkin(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        query_db(
            "UPDATE private_training_subscriptions SET status = 'CANCELLED' WHERE id = %s",
            (subscription["id"],),
            commit=True,
        )
        with self.assertRaises(PrivateTrainingCancelledError):
            self._check_in(subscription["id"])

    def test_33_portal_token_raw_value_is_not_stored(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        token_result = generate_portal_token(self.trainer_a_user, subscription["id"])
        self.assertIn("raw_token", token_result)
        self.assertNotEqual(token_result["raw_token"], token_result["token"]["token_hash"])

    def test_34_portal_token_hash_resolves_correctly(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        token_result = generate_portal_token(self.trainer_a_user, subscription["id"])
        resolved = resolve_portal_token(token_result["raw_token"])
        self.assertEqual(resolved["subscription"]["id"], subscription["id"])
        self.assertEqual(resolved["subscription"]["member_id"], self.member_a_id)

    def test_35_regenerated_token_invalidates_old_token(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        first = generate_portal_token(self.trainer_a_user, subscription["id"])
        second = generate_portal_token(self.trainer_a_user, subscription["id"])
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(first["raw_token"])
        resolved = resolve_portal_token(second["raw_token"])
        self.assertEqual(resolved["subscription"]["id"], subscription["id"])

    def test_36_revoke_invalidates_token(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        token_result = generate_portal_token(self.trainer_a_user, subscription["id"])
        revoke_result = revoke_portal_token(self.trainer_a_user, subscription["id"])
        self.assertGreaterEqual(revoke_result["revoked_count"], 1)
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(token_result["raw_token"])

    def test_37_completed_subscription_token_no_longer_resolves(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, 1, 0, 30)
        token_result = generate_portal_token(self.trainer_a_user, subscription["id"])
        session_row = self._check_in(subscription["id"])
        self._approve(subscription["id"], session_row["id"])
        with self.assertRaises(PrivateTrainingCompletedError):
            resolve_portal_token(token_result["raw_token"])

    def test_38_expired_subscription_token_no_longer_resolves(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        token_result = generate_portal_token(self.trainer_a_user, subscription["id"])
        self._expire_subscription(subscription["id"])
        with self.assertRaises(PrivateTrainingExpiredError):
            resolve_portal_token(token_result["raw_token"])

    def test_39_wrong_trainer_cannot_generate_or_revoke_token(self):
        subscription = self._make_active_subscription(self.member_a_id, trainer_user_id=self.trainer_a_user_id, total_sessions=2)
        with self.assertRaises(PrivateTrainingForbiddenError):
            generate_portal_token(self.trainer_b_user, subscription["id"])
        with self.assertRaises(PrivateTrainingForbiddenError):
            revoke_portal_token(self.trainer_b_user, subscription["id"])

    def test_40_regression_existing_member_and_attendance_tables_intact(self):
        member = query_db("SELECT * FROM members WHERE id = %s", (self.member_a_id,), one=True)
        attendance = query_db("SELECT COUNT(*) AS count FROM attendance", one=True)
        self.assertIsNotNone(member)
        self.assertIsNotNone(attendance)

    def test_41_concurrent_approvals_consume_once(self):
        subscription = self._create_subscription(self.member_e_id, self.trainer_a_user_id, 1, 0, 30)
        session_row = self._check_in(subscription["id"])
        barrier = threading.Barrier(2)
        outcomes = []
        errors = []

        def worker():
            try:
                barrier.wait()
                outcomes.append(self._approve(subscription["id"], session_row["id"]))
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 1)
        self.assertEqual(counts["remaining_sessions"], 0)
        self.assertEqual(len(outcomes), 2)
        self.assertEqual(len(errors), 0)
        self.assertTrue(any(item["outcome"] == "approved" for item in outcomes))
        self.assertTrue(any(item["outcome"] == "already_approved" for item in outcomes))


if __name__ == "__main__":
    unittest.main()
