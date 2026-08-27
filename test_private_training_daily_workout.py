import re
import unittest
from datetime import timedelta
from urllib.parse import urlparse

from psycopg2.extras import Json

from system_app.app import app
from system_app.queries import query_db
from system_app.private_training.services import (
    PrivateTrainingForbiddenError,
    PrivateTrainingValidationError,
    approve_private_training_session,
    cancel_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_subscription,
    get_private_training_pending_session,
    get_private_training_subscription,
    reject_private_training_session,
)


class PrivateTrainingDailyWorkoutTest(unittest.TestCase):
    manager_user_id = 966001
    trainer_user_id = 966002
    trainer_b_user_id = 966003
    viewer_user_id = 966004
    super_admin_user_id = 966005
    no_perm_user_id = 966006

    member_a_id = 967001
    member_b_id = 967002
    member_c_id = 967003
    member_d_id = 967004
    member_e_id = 967005
    member_f_id = 967006

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
        self.trainer_b_user = self._load_user(self.trainer_b_user_id)
        self.viewer_user = self._load_user(self.viewer_user_id)
        self.super_admin_user = self._load_user(self.super_admin_user_id)
        self.no_perm_user = self._load_user(self.no_perm_user_id)

    def tearDown(self):
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        app.config["TESTING"] = self._old_testing
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf

    def _today(self):
        from system_app.func import get_cairo_date

        return get_cairo_date()

    def _date_str(self, delta_days: int):
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

    def _portal_url_from_html(self, html: str) -> tuple[str, str]:
        match = re.search(r'value="(https?://[^"]+/private-training/member/([A-Za-z0-9_-]+))"', html)
        self.assertIsNotNone(match, "Expected generated member portal URL")
        return match.group(1), match.group(2)

    def _upsert_users(self):
        users = [
            (self.manager_user_id, "ptw_manager", {"private_training_manage": True}),
            (self.trainer_user_id, "ptw_trainer_a", {"private_training_trainer": True}),
            (self.trainer_b_user_id, "ptw_trainer_b", {"private_training_trainer": True}),
            (self.viewer_user_id, "ptw_viewer", {"private_training_view": True}),
            (self.super_admin_user_id, "ptw_super_admin", {"super_admin": True}),
            (self.no_perm_user_id, "ptw_no_perm", {}),
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
                (member_id, f"PTW Member {index}", f"8800{index:02d}", self._date_str(-1), self._date_str(30)),
                commit=True,
            )

    def _cleanup_private_training(self):
        query_db(
            """
            DELETE FROM private_training_daily_workouts
            WHERE subscription_id IN (
                SELECT id
                FROM private_training_subscriptions
                WHERE member_id BETWEEN 967001 AND 967006
                   OR trainer_user_id BETWEEN 966001 AND 966006
                   OR created_by_user_id BETWEEN 966001 AND 966006
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_portal_tokens
            WHERE subscription_id IN (
                SELECT id
                FROM private_training_subscriptions
                WHERE member_id BETWEEN 967001 AND 967006
                   OR trainer_user_id BETWEEN 966001 AND 966006
                   OR created_by_user_id BETWEEN 966001 AND 966006
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
                WHERE member_id BETWEEN 967001 AND 967006
                   OR trainer_user_id BETWEEN 966001 AND 966006
                   OR created_by_user_id BETWEEN 966001 AND 966006
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE member_id BETWEEN 967001 AND 967006
               OR trainer_user_id BETWEEN 966001 AND 966006
               OR created_by_user_id BETWEEN 966001 AND 966006
            """,
            commit=True,
        )

    def _cleanup_members(self):
        query_db("DELETE FROM members WHERE id BETWEEN 967001 AND 967006", commit=True)

    def _cleanup_users(self):
        query_db("DELETE FROM users WHERE id BETWEEN 966001 AND 966006", commit=True)

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_subscription(
        self,
        member_id,
        *,
        trainer_user_id=None,
        total_sessions=2,
        start_offset_days=0,
        expiry_offset_days=30,
        creator=None,
    ):
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

    def _make_active_subscription(self, member_id, *, trainer_user_id=None, total_sessions=2, creator=None):
        return self._create_subscription(
            member_id,
            trainer_user_id=trainer_user_id or self.trainer_user_id,
            total_sessions=total_sessions,
            start_offset_days=0,
            expiry_offset_days=30,
            creator=creator,
        )

    def _make_future_subscription(self, member_id, *, trainer_user_id=None, total_sessions=2, creator=None):
        return self._create_subscription(
            member_id,
            trainer_user_id=trainer_user_id or self.trainer_user_id,
            total_sessions=total_sessions,
            start_offset_days=2,
            expiry_offset_days=30,
            creator=creator,
        )

    def _detail_client(self, user, subscription_id):
        client = app.test_client()
        self._login_as(client, user)
        response = client.get(f"/private-training/subscriptions/{subscription_id}")
        return client, response

    def _check_in_via_route(self, client, subscription_id, csrf_token, workout_name, follow_redirects=True):
        return client.post(
            f"/private-training/subscriptions/{subscription_id}/check-in",
            data={
                "csrf_token": csrf_token,
                "workout_name": workout_name,
            },
            follow_redirects=follow_redirects,
        )

    def _generate_portal(self, subscription_id):
        client = app.test_client()
        self._login_as(client, self.trainer_user)
        detail = client.get(f"/private-training/subscriptions/{subscription_id}")
        csrf = self._csrf_from_html(detail.data.decode())
        response = client.post(
            f"/private-training/subscriptions/{subscription_id}/portal-token",
            data={"csrf_token": csrf},
        )
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        portal_url, raw_token = self._portal_url_from_html(html)
        return client, csrf, portal_url, raw_token

    def _insert_legacy_approved_session_without_workout(self, subscription_id, trainer_user_id):
        return query_db(
            """
            INSERT INTO private_training_sessions (
                subscription_id, trainer_user_id, workout_name, checked_in_at, status,
                approved_at, rejected_at, rejection_reason, created_at, updated_at
            ) VALUES (%s, %s, NULL, CURRENT_TIMESTAMP, 'APPROVED', CURRENT_TIMESTAMP, NULL, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            RETURNING id
            """,
            (subscription_id, trainer_user_id),
            commit=True,
            one=True,
        )

    def test_01_check_in_requires_workout_name_and_creates_no_session(self):
        subscription = self._make_active_subscription(self.member_a_id)

        with self.assertRaises(PrivateTrainingValidationError):
            create_private_training_session_checkin(self.trainer_user, subscription["id"], None)
        with self.assertRaises(PrivateTrainingValidationError):
            create_private_training_session_checkin(self.trainer_user, subscription["id"], "   ")
        with self.assertRaises(PrivateTrainingValidationError):
            create_private_training_session_checkin(self.trainer_user, subscription["id"], "x" * 256)

        rows = query_db(
            "SELECT * FROM private_training_sessions WHERE subscription_id = %s",
            (subscription["id"],),
        ) or []
        self.assertEqual(rows, [])

    def test_02_check_in_route_requires_csrf(self):
        subscription = self._make_active_subscription(self.member_b_id)
        client, _ = self._detail_client(self.trainer_user, subscription["id"])
        response = client.post(
            f"/private-training/subscriptions/{subscription['id']}/check-in",
            data={"workout_name": "Chest"},
        )
        self.assertEqual(response.status_code, 400)

    def test_03_valid_workout_check_in_trims_and_persists_pending_snapshot(self):
        subscription = self._make_active_subscription(self.member_c_id)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        response = self._check_in_via_route(client, subscription["id"], csrf, " Chest ")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("Waiting for Member Approval", html)
        self.assertIn("Workout: Chest", html)
        self.assertIn("Workout", html)
        self.assertNotIn("Rejected At", html)
        self.assertNotIn("Reason", html)

        pending = get_private_training_pending_session(subscription["id"])
        self.assertIsNotNone(pending)
        self.assertEqual(pending["workout_name"], "Chest")
        counts = get_private_training_subscription(subscription["id"])
        self.assertEqual(counts["approved_count"], 0)
        self.assertEqual(counts["remaining_sessions"], 2)

    def test_04_approval_preserves_workout_and_history_displays_it(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=2)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Leg Day")
        approve_private_training_session(subscription["id"], pending["id"], {"subscription_id": subscription["id"]})

        session_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (pending["id"],), one=True)
        self.assertEqual(session_row["workout_name"], "Leg Day")
        self.assertEqual(session_row["status"], "APPROVED")

        staff_html = self._detail_client(self.trainer_user, subscription["id"])[1].data.decode()
        self.assertIn("Workout", staff_html)
        self.assertIn("Leg Day", staff_html)
        self.assertNotIn("Rejected At", staff_html)
        self.assertNotIn("Reason", staff_html)

        _, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        portal_html = app.test_client().get(urlparse(portal_url).path).data.decode()
        self.assertIn("Workout", portal_html)
        self.assertIn("Leg Day", portal_html)
        self.assertNotIn("Rejected At", portal_html)
        self.assertNotIn("Reason", portal_html)

        subscription_row = get_private_training_subscription(subscription["id"])
        self.assertEqual(subscription_row["approved_count"], 1)
        self.assertEqual(subscription_row["remaining_sessions"], 1)

    def test_05_same_day_second_session_preserves_its_own_workout_snapshot(self):
        subscription = self._make_active_subscription(self.member_e_id, total_sessions=2)
        first_pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Chest")
        approve_private_training_session(subscription["id"], first_pending["id"], {"subscription_id": subscription["id"]})
        second_pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Cardio")
        approve_private_training_session(subscription["id"], second_pending["id"], {"subscription_id": subscription["id"]})

        rows = query_db(
            """
            SELECT workout_name, status
            FROM private_training_sessions
            WHERE subscription_id = %s
            ORDER BY id ASC
            """,
            (subscription["id"],),
        ) or []
        self.assertEqual([row["workout_name"] for row in rows], ["Chest", "Cardio"])
        self.assertEqual([row["status"] for row in rows], ["APPROVED", "APPROVED"])

        subscription_row = get_private_training_subscription(subscription["id"])
        self.assertEqual(subscription_row["approved_count"], 2)
        self.assertEqual(subscription_row["remaining_sessions"], 0)
        self.assertEqual(subscription_row["effective_status"], "COMPLETED")

    def test_06_unrelated_trainer_and_view_only_cannot_check_in(self):
        subscription = self._make_active_subscription(self.member_f_id)
        with self.assertRaises(PrivateTrainingForbiddenError):
            create_private_training_session_checkin(self.trainer_b_user, subscription["id"], "Arms")
        with self.assertRaises(PrivateTrainingForbiddenError):
            create_private_training_session_checkin(self.viewer_user, subscription["id"], "Arms")

        rows = query_db("SELECT * FROM private_training_sessions WHERE subscription_id = %s", (subscription["id"],), one=True)
        self.assertIsNone(rows)

    def test_07_manager_cannot_check_in_but_super_admin_can(self):
        subscription = self._make_active_subscription(self.member_a_id)
        with self.assertRaises(PrivateTrainingForbiddenError):
            create_private_training_session_checkin(self.manager_user, subscription["id"], "Workout")

        pending = create_private_training_session_checkin(self.super_admin_user, subscription["id"], "Recovery Day")
        self.assertEqual(pending["workout_name"], "Recovery Day")
        self.assertEqual(pending["status"], "PENDING_MEMBER_APPROVAL")

    def test_08_member_portal_displays_pending_workout_and_is_read_only(self):
        subscription = self._make_active_subscription(self.member_b_id)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())
        self._check_in_via_route(client, subscription["id"], csrf, "Push Day")

        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        response = portal_client.get(urlparse(portal_url).path)
        html = response.data.decode()
        self.assertIn("Pending Member Approval", html)
        self.assertIn("Workout: Push Day", html)
        self.assertIn("Approve Session", html)
        self.assertNotIn("Reject Session", html)
        self.assertNotIn("Save Workout", html)
        self.assertNotIn("/today-workout", html)
        self.assertNotIn("<textarea", html.lower())
        self.assertNotIn("Rejected At", html)
        self.assertNotIn("Reason", html)

    def test_09_staff_history_displays_workout_and_no_rejection_columns(self):
        subscription = self._make_active_subscription(self.member_c_id)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Back Day")
        approve_private_training_session(subscription["id"], pending["id"], {"subscription_id": subscription["id"]})

        response = self._detail_client(self.trainer_user, subscription["id"])[1]
        html = response.data.decode()
        self.assertIn("Workout", html)
        self.assertIn("Back Day", html)
        self.assertNotIn("Rejected At", html)
        self.assertNotIn("Reason", html)

    def test_10_rejected_history_stays_internal_and_hidden_from_member_portal(self):
        subscription = self._make_active_subscription(self.member_d_id)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Recovery")
        reject_private_training_session(
            subscription["id"],
            pending["id"],
            "Member requested a different time",
            {"subscription_id": subscription["id"]},
        )

        session_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (pending["id"],), one=True)
        self.assertEqual(session_row["status"], "REJECTED")
        self.assertEqual(session_row["rejection_reason"], "Member requested a different time")

        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        html = portal_client.get(urlparse(portal_url).path).data.decode()
        self.assertNotIn("REJECTED", html)
        self.assertNotIn("Rejected At", html)
        self.assertNotIn("Reason", html)
        self.assertNotIn("rejection_reason", html.lower())

    def test_11_legacy_null_workout_displays_dash(self):
        subscription = self._make_active_subscription(self.member_e_id)
        legacy_row = self._insert_legacy_approved_session_without_workout(subscription["id"], self.trainer_user_id)

        staff_html = self._detail_client(self.trainer_user, subscription["id"])[1].data.decode()
        self.assertRegex(
            staff_html,
            re.compile(rf"<td>\s*{legacy_row['id']}\s*</td>.*?<td>\s*-\s*</td>", re.S),
        )

        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        portal_html = portal_client.get(urlparse(portal_url).path).data.decode()
        self.assertRegex(
            portal_html,
            re.compile(r"<td>\s*-\s*</td>", re.S),
        )

    def test_12_cancellation_and_completion_preserve_historical_workout(self):
        cancelled_subscription = self._make_active_subscription(self.member_f_id)

        # Cancellation path
        pending = create_private_training_session_checkin(self.trainer_user, cancelled_subscription["id"], "Upper Body")
        approve_private_training_session(
            cancelled_subscription["id"],
            pending["id"],
            {"subscription_id": cancelled_subscription["id"]},
        )
        cancel_private_training_subscription(self.manager_user, cancelled_subscription["id"])
        cancelled_session = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (pending["id"],), one=True)
        self.assertEqual(cancelled_session["workout_name"], "Upper Body")
        self.assertEqual(get_private_training_subscription(cancelled_subscription["id"])["status"], "CANCELLED")

        # Completion path
        completed = self._make_active_subscription(self.member_a_id, total_sessions=1)
        completed_pending = create_private_training_session_checkin(self.trainer_user, completed["id"], "Lower Body")
        approve_private_training_session(
            completed["id"],
            completed_pending["id"],
            {"subscription_id": completed["id"]},
        )
        completed_session = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (completed_pending["id"],), one=True)
        self.assertEqual(completed_session["workout_name"], "Lower Body")
        self.assertEqual(get_private_training_subscription(completed["id"])["status"], "COMPLETED")

    def test_13_old_member_reject_endpoint_still_returns_404(self):
        subscription = self._make_active_subscription(self.member_b_id)
        portal_client, csrf, portal_url, raw_token = self._generate_portal(subscription["id"])
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Boxing")

        response = portal_client.post(
            f"/private-training/member/{raw_token}/sessions/{pending['id']}/reject",
            data={
                "csrf_token": csrf,
                "rejection_reason": "Not needed",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(get_private_training_pending_session(subscription["id"])["id"], pending["id"])


if __name__ == "__main__":
    unittest.main()
