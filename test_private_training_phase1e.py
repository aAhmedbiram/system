import re
import unittest
from datetime import timedelta
from urllib.parse import urlparse

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.private_training.services import (
    PrivateTrainingCancelledError,
    PrivateTrainingCompletedError,
    PrivateTrainingExpiredError,
    PrivateTrainingForbiddenError,
    PrivateTrainingNotFoundError,
    approve_private_training_session,
    cancel_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_subscription,
    generate_portal_token,
    get_private_training_pending_session,
    get_private_training_subscription,
    reject_private_training_session,
)


class PrivateTrainingPhase1ETest(unittest.TestCase):
    manager_user_id = 993001
    trainer_user_id = 993002
    no_perm_user_id = 993003
    super_admin_user_id = 993004

    member_a_id = 994001
    member_b_id = 994002
    member_c_id = 994003
    member_d_id = 994004
    member_e_id = 994005
    member_f_id = 994006

    def setUp(self):
        self._old_testing = app.config.get("TESTING")
        self._old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = True

        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        self._upsert_users()
        self._upsert_members()

        self.manager_user = self._load_user(self.manager_user_id)
        self.trainer_user = self._load_user(self.trainer_user_id)
        self.no_perm_user = self._load_user(self.no_perm_user_id)
        self.super_admin_user = self._load_user(self.super_admin_user_id)

    def tearDown(self):
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        app.config["TESTING"] = self._old_testing
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf

    def _today(self):
        return get_cairo_date()

    def _date_str(self, delta_days: int) -> str:
        return (self._today() + timedelta(days=delta_days)).strftime("%Y-%m-%d")

    def _login_as(self, client, user):
        with client.session_transaction() as sess:
            sess["user_id"] = user["id"]
            sess["username"] = user["username"]

    def _csrf_from_html(self, html: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', html)
        if not match:
            match = re.search(r'<meta name="csrf-token" content="([^"]+)">', html)
        self.assertIsNotNone(match, "Expected csrf token in rendered HTML")
        return match.group(1)

    def _upsert_users(self):
        users = [
            (self.manager_user_id, "pte_manager", {"private_training_manage": True}),
            (self.trainer_user_id, "pte_trainer", {"private_training_trainer": True}),
            (self.no_perm_user_id, "pte_no_perm", {}),
            (self.super_admin_user_id, "pte_super_admin", {"super_admin": True}),
        ]
        for user_id, username, permissions in users:
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
                (user_id, username, f"{username}@test.local", "pwd", Json(permissions)),
                commit=True,
            )

    def _upsert_members(self):
        for index, member_id in enumerate(
            [
                self.member_a_id,
                self.member_b_id,
                self.member_c_id,
                self.member_d_id,
                self.member_e_id,
                self.member_f_id,
            ],
            start=1,
        ):
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
                (member_id, f"PTE Member {index}", f"7700{index:02d}", self._date_str(-1), self._date_str(30)),
                commit=True,
            )

    def _cleanup_private_training(self):
        query_db(
            """
            DELETE FROM private_training_portal_tokens
            WHERE subscription_id IN (
                SELECT id
                FROM private_training_subscriptions
                WHERE member_id BETWEEN 994001 AND 994006
                   OR trainer_user_id BETWEEN 993001 AND 993004
                   OR created_by_user_id BETWEEN 993001 AND 993004
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_sessions
            WHERE subscription_id IN (
                SELECT id
                FROM private_training_subscriptions
                WHERE member_id BETWEEN 994001 AND 994006
                   OR trainer_user_id BETWEEN 993001 AND 993004
                   OR created_by_user_id BETWEEN 993001 AND 993004
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE member_id BETWEEN 994001 AND 994006
               OR trainer_user_id BETWEEN 993001 AND 993004
               OR created_by_user_id BETWEEN 993001 AND 993004
            """,
            commit=True,
        )

    def _cleanup_members(self):
        query_db("DELETE FROM members WHERE id BETWEEN 994001 AND 994006", commit=True)

    def _cleanup_users(self):
        query_db("DELETE FROM users WHERE id BETWEEN 993001 AND 993004", commit=True)

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_subscription(self, member_id, *, trainer_user_id=None, total_sessions=2, start_offset_days=0, expiry_offset_days=30, creator=None):
        creator = creator or self.manager_user
        result = create_private_training_subscription(
            creator,
            member_id,
            trainer_user_id or self.trainer_user_id,
            total_sessions,
            self._date_str(start_offset_days),
            self._date_str(expiry_offset_days),
        )
        return result["subscription"]

    def _make_active_subscription(self, member_id, *, total_sessions=2, trainer_user_id=None, creator=None):
        return self._create_subscription(
            member_id,
            trainer_user_id=trainer_user_id or self.trainer_user_id,
            total_sessions=total_sessions,
            start_offset_days=0,
            expiry_offset_days=30,
            creator=creator,
        )

    def _make_future_subscription(self, member_id, *, total_sessions=2, trainer_user_id=None):
        return self._create_subscription(
            member_id,
            trainer_user_id=trainer_user_id or self.trainer_user_id,
            total_sessions=total_sessions,
            start_offset_days=2,
            expiry_offset_days=30,
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

    def _detail_client(self, user, subscription_id):
        client = app.test_client()
        self._login_as(client, user)
        response = client.get(f"/private-training/subscriptions/{subscription_id}")
        return client, response

    def _portal_client_and_html(self, subscription_id):
        client = app.test_client()
        self._login_as(client, self.trainer_user)
        detail = client.get(f"/private-training/subscriptions/{subscription_id}")
        csrf = self._csrf_from_html(detail.data.decode())
        generated = client.post(
            f"/private-training/subscriptions/{subscription_id}/portal-token",
            data={"csrf_token": csrf},
        )
        self.assertEqual(generated.status_code, 200)
        html = generated.data.decode()
        match = re.search(r'value="(https?://[^"]+/private-training/member/([A-Za-z0-9_-]+))"', html)
        self.assertIsNotNone(match)
        return client, csrf, match.group(1), match.group(2)

    def _cancel_with_manager(self, subscription_id):
        client, response = self._detail_client(self.manager_user, subscription_id)
        csrf = self._csrf_from_html(response.data.decode())
        cancel_response = client.post(
            f"/private-training/subscriptions/{subscription_id}/cancel",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        return cancel_response

    def test_01_manager_can_cancel_assigned_and_active_subscriptions(self):
        assigned = self._make_future_subscription(self.member_a_id)
        assigned_response = self._cancel_with_manager(assigned["id"])
        self.assertEqual(assigned_response.status_code, 200)
        assigned_row = get_private_training_subscription(assigned["id"])
        self.assertEqual(assigned_row["status"], "CANCELLED")
        self.assertIn("CANCELLED", assigned_response.data.decode())

        active = self._make_active_subscription(self.member_b_id)
        active_response = self._cancel_with_manager(active["id"])
        self.assertEqual(active_response.status_code, 200)
        active_row = get_private_training_subscription(active["id"])
        self.assertEqual(active_row["status"], "CANCELLED")

    def test_02_route_is_post_only_and_csrf_protected(self):
        subscription = self._make_active_subscription(self.member_c_id)
        client, response = self._detail_client(self.manager_user, subscription["id"])
        self.assertEqual(client.get(f"/private-training/subscriptions/{subscription['id']}/cancel").status_code, 405)
        self.assertEqual(
            client.post(f"/private-training/subscriptions/{subscription['id']}/cancel", data={}).status_code,
            400,
        )
        self.assertEqual(get_private_training_subscription(subscription["id"])["status"], "ACTIVE")

    def test_03_unauthorized_and_trainer_only_users_cannot_cancel(self):
        subscription = self._make_active_subscription(self.member_d_id)

        no_perm_service_client = self.no_perm_user
        with self.assertRaises(PrivateTrainingForbiddenError):
            cancel_private_training_subscription(no_perm_service_client, subscription["id"])

        trainer_client, response = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(response.data.decode())
        trainer_cancel = trainer_client.post(
            f"/private-training/subscriptions/{subscription['id']}/cancel",
            data={"csrf_token": csrf},
            follow_redirects=True,
        )
        self.assertIn("You do not have permission", trainer_cancel.data.decode())
        self.assertEqual(get_private_training_subscription(subscription["id"])["status"], "ACTIVE")

    def test_04_cancellation_preserves_history_and_pending_rows(self):
        subscription = self._make_active_subscription(self.member_e_id, total_sessions=3)

        first_pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Chest")
        approve_private_training_session(subscription["id"], first_pending["id"], {"subscription_id": subscription["id"]})

        second_pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Back")
        reject_private_training_session(
            subscription["id"],
            second_pending["id"],
            "Trainer needs to reschedule",
            {"subscription_id": subscription["id"]},
        )

        third_pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Leg Day")
        token_client, portal_csrf, portal_url, raw_token = self._portal_client_and_html(subscription["id"])
        self.assertIn(raw_token, portal_url)

        before = get_private_training_subscription(subscription["id"])
        self.assertEqual(before["approved_count"], 1)
        self.assertEqual(before["remaining_sessions"], 2)

        cancel_response = self._cancel_with_manager(subscription["id"])
        self.assertEqual(cancel_response.status_code, 200)
        after = get_private_training_subscription(subscription["id"])
        self.assertEqual(after["status"], "CANCELLED")
        self.assertEqual(after["approved_count"], 1)
        self.assertEqual(after["remaining_sessions"], 2)
        self.assertEqual(after["total_sessions"], 3)

        approved_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (first_pending["id"],), one=True)
        rejected_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (second_pending["id"],), one=True)
        pending_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (third_pending["id"],), one=True)
        self.assertEqual(approved_row["trainer_user_id"], self.trainer_user_id)
        self.assertEqual(approved_row["status"], "APPROVED")
        self.assertEqual(approved_row["workout_name"], "Chest")
        self.assertEqual(rejected_row["trainer_user_id"], self.trainer_user_id)
        self.assertEqual(rejected_row["status"], "REJECTED")
        self.assertEqual(rejected_row["workout_name"], "Back")
        self.assertEqual(rejected_row["rejection_reason"], "Trainer needs to reschedule")
        self.assertEqual(pending_row["trainer_user_id"], self.trainer_user_id)
        self.assertEqual(pending_row["status"], "PENDING_MEMBER_APPROVAL")
        self.assertEqual(pending_row["workout_name"], "Leg Day")

        refreshed_client = app.test_client()
        self._login_as(refreshed_client, self.trainer_user)
        detail_html = refreshed_client.get(f"/private-training/subscriptions/{subscription['id']}").data.decode()
        self.assertIn("CANCELLED", detail_html)
        self.assertIn("REJECTED", detail_html)
        self.assertNotIn("<th>Rejected At</th>", detail_html)
        self.assertNotIn("<th>Reason</th>", detail_html)
        self.assertNotIn("Cancel Subscription", detail_html)

        with self.assertRaises(PrivateTrainingCancelledError):
            create_private_training_session_checkin(self.trainer_user, subscription["id"], "Workout")

        portal_response = token_client.get(urlparse(portal_url).path)
        self.assertEqual(portal_response.status_code, 410)

        approve_response = token_client.post(
            f"/private-training/member/{raw_token}/sessions/{third_pending['id']}/approve",
            data={"csrf_token": portal_csrf},
        )
        self.assertEqual(approve_response.status_code, 410)
        reject_response = token_client.post(
            f"/private-training/member/{raw_token}/sessions/{third_pending['id']}/reject",
            data={"csrf_token": portal_csrf, "rejection_reason": "No longer needed"},
        )
        self.assertEqual(reject_response.status_code, 404)

    def test_05_completed_and_expired_cannot_cancel(self):
        completed = self._make_active_subscription(self.member_f_id, total_sessions=1)
        pending = create_private_training_session_checkin(self.trainer_user, completed["id"], "Upper")
        approve_private_training_session(completed["id"], pending["id"], {"subscription_id": completed["id"]})
        with self.assertRaises(PrivateTrainingCompletedError):
            cancel_private_training_subscription(self.manager_user, completed["id"])

        expired = self._make_active_subscription(self.member_a_id)
        self._expire_subscription(expired["id"])
        with self.assertRaises(PrivateTrainingExpiredError):
            cancel_private_training_subscription(self.manager_user, expired["id"])

    def test_06_repeated_cancellation_is_safely_rejected(self):
        subscription = self._make_active_subscription(self.member_b_id)
        first = cancel_private_training_subscription(self.manager_user, subscription["id"])
        self.assertEqual(first["subscription"]["status"], "CANCELLED")
        with self.assertRaises(PrivateTrainingCancelledError):
            cancel_private_training_subscription(self.manager_user, subscription["id"])
        self.assertEqual(get_private_training_subscription(subscription["id"])["status"], "CANCELLED")

    def test_07_manager_can_cancel_subscription_and_detail_updates(self):
        subscription = self._make_active_subscription(self.member_c_id)
        response = self._cancel_with_manager(subscription["id"])
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("CANCELLED", html)
        self.assertNotIn("Cancel Subscription", html)

    def test_08_cancelled_subscription_blocks_trainer_checkin_and_public_portal(self):
        subscription = self._make_active_subscription(self.member_d_id)
        token_client, portal_csrf, portal_url, raw_token = self._portal_client_and_html(subscription["id"])
        cancel_private_training_subscription(self.super_admin_user, subscription["id"])

        with self.assertRaises(PrivateTrainingCancelledError):
            create_private_training_session_checkin(self.trainer_user, subscription["id"], "Workout")

        self.assertEqual(token_client.get(urlparse(portal_url).path).status_code, 410)

        # The old portal token must no longer authorize approve/reject.
        self.assertEqual(token_client.post(
            f"/private-training/member/{raw_token}/sessions/1/approve",
            data={"csrf_token": portal_csrf},
        ).status_code, 410)
        self.assertEqual(token_client.post(
            f"/private-training/member/{raw_token}/sessions/1/reject",
            data={"csrf_token": portal_csrf, "rejection_reason": "irrelevant"},
        ).status_code, 404)
