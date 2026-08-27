import re
import unittest
from datetime import timedelta
from unittest.mock import patch
from urllib.parse import urlparse

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.private_training.services import (
    PrivateTrainingValidationError,
    approve_private_training_session,
    cancel_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_subscription,
    get_private_training_daily_workout,
    get_private_training_pending_session,
    get_private_training_subscription,
    get_private_training_todays_workout,
    reject_private_training_session,
    save_private_training_todays_workout,
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

    def _save_today_workout_via_route(self, client, subscription_id, csrf_token, workout_name, follow_redirects=True):
        return client.post(
            f"/private-training/subscriptions/{subscription_id}/today-workout",
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

    def test_01_trainer_can_create_todays_workout_for_own_subscription(self):
        subscription = self._make_active_subscription(self.member_a_id)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        response = self._save_today_workout_via_route(client, subscription["id"], csrf, " Chest ")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("Today's Workout", html)
        self.assertIn("Chest", html)

        workout = get_private_training_todays_workout(subscription["id"])
        self.assertIsNotNone(workout)
        self.assertEqual(workout["workout_name"], "Chest")

    def test_01b_today_workout_route_requires_csrf(self):
        subscription = self._make_active_subscription(self.member_b_id)
        client, _ = self._detail_client(self.trainer_user, subscription["id"])
        response = client.post(
            f"/private-training/subscriptions/{subscription['id']}/today-workout",
            data={"workout_name": "Chest"},
        )
        self.assertEqual(response.status_code, 400)

    def test_02_same_day_update_overwrites_value_without_duplicate_row(self):
        subscription = self._make_active_subscription(self.member_b_id)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        self._save_today_workout_via_route(client, subscription["id"], csrf, "Push Day")
        self._save_today_workout_via_route(client, subscription["id"], csrf, "Back & Biceps")

        rows = query_db(
            """
            SELECT id, workout_name
            FROM private_training_daily_workouts
            WHERE subscription_id = %s
              AND workout_date = %s
            ORDER BY id ASC
            """,
            (subscription["id"], self._today()),
        ) or []
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["workout_name"], "Back & Biceps")

    def test_03_unrelated_trainer_cannot_modify_another_trainer_subscription(self):
        subscription = self._make_active_subscription(self.member_c_id)
        client = app.test_client()
        self._login_as(client, self.trainer_b_user)
        trainer_page = client.get("/private-training/my-clients")
        csrf = self._csrf_from_html(trainer_page.data.decode())

        response = self._save_today_workout_via_route(client, subscription["id"], csrf, "Arms Day")
        self.assertIn(response.status_code, (200, 302))
        workout = get_private_training_todays_workout(subscription["id"])
        self.assertIsNone(workout)

    def test_04_view_only_user_cannot_modify_workout(self):
        subscription = self._make_active_subscription(self.member_d_id)
        client, detail = self._detail_client(self.viewer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        response = self._save_today_workout_via_route(client, subscription["id"], csrf, "Rest Day")
        self.assertIn(response.status_code, (200, 302))
        workout = get_private_training_todays_workout(subscription["id"])
        self.assertIsNone(workout)

    def test_05_manager_can_save_workout(self):
        subscription = self._make_active_subscription(self.member_e_id)
        client, detail = self._detail_client(self.manager_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        response = self._save_today_workout_via_route(client, subscription["id"], csrf, "Leg Day")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Leg Day", response.data.decode())
        self.assertEqual(get_private_training_todays_workout(subscription["id"])["workout_name"], "Leg Day")

    def test_06_super_admin_can_save_workout(self):
        subscription = self._make_active_subscription(self.member_f_id)
        client, detail = self._detail_client(self.super_admin_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())

        response = self._save_today_workout_via_route(client, subscription["id"], csrf, "Recovery Day")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Recovery Day", response.data.decode())
        self.assertEqual(get_private_training_todays_workout(subscription["id"])["workout_name"], "Recovery Day")

    def test_07_subscription_detail_displays_today_workout(self):
        subscription = self._make_active_subscription(self.member_a_id, creator=self.manager_user)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())
        self._save_today_workout_via_route(client, subscription["id"], csrf, "Upper Body")

        response = client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Today's Workout", html)
        self.assertIn("Upper Body", html)
        self.assertIn("Save Workout", html)

    def test_08_member_portal_displays_today_workout_read_only(self):
        subscription = self._make_active_subscription(self.member_b_id)
        client, detail = self._detail_client(self.trainer_user, subscription["id"])
        csrf = self._csrf_from_html(detail.data.decode())
        self._save_today_workout_via_route(client, subscription["id"], csrf, "Push Day")

        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        response = portal_client.get(urlparse(portal_url).path)
        html = response.data.decode()
        self.assertIn("Today's Workout", html)
        self.assertIn("Push Day", html)
        self.assertNotIn("Save Workout", html)
        self.assertNotIn("/today-workout", html)
        self.assertNotIn("<textarea", html.lower())

    def test_09_member_portal_shows_empty_state_when_no_workout(self):
        subscription = self._make_active_subscription(self.member_c_id)
        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        response = portal_client.get(urlparse(portal_url).path)
        html = response.data.decode()
        self.assertIn("Today's Workout", html)
        self.assertIn("No workout assigned for today.", html)

    def test_10_blank_workout_is_rejected(self):
        subscription = self._make_active_subscription(self.member_d_id)
        with self.assertRaises(PrivateTrainingValidationError):
            save_private_training_todays_workout(self.trainer_user, subscription["id"], "   ")

    def test_11_workout_whitespace_is_trimmed(self):
        subscription = self._make_active_subscription(self.member_e_id)
        result = save_private_training_todays_workout(self.trainer_user, subscription["id"], "   Back Day   ")
        self.assertEqual(result["workout"]["workout_name"], "Back Day")

    def test_12_long_workout_is_rejected(self):
        subscription = self._make_active_subscription(self.member_f_id)
        with self.assertRaises(PrivateTrainingValidationError):
            save_private_training_todays_workout(self.trainer_user, subscription["id"], "x" * 256)

    def test_13_next_cairo_day_creates_a_new_row(self):
        subscription = self._make_active_subscription(self.member_a_id, creator=self.manager_user)
        save_private_training_todays_workout(self.trainer_user, subscription["id"], "Chest")

        tomorrow = self._today() + timedelta(days=1)
        with patch("system_app.private_training.services.get_cairo_date", return_value=tomorrow):
            save_private_training_todays_workout(self.trainer_user, subscription["id"], "Back")

        today_row = get_private_training_daily_workout(subscription["id"], self._today())
        tomorrow_row = get_private_training_daily_workout(subscription["id"], tomorrow)
        self.assertIsNotNone(today_row)
        self.assertIsNotNone(tomorrow_row)
        self.assertEqual(today_row["workout_name"], "Chest")
        self.assertEqual(tomorrow_row["workout_name"], "Back")

    def test_14_workout_saving_does_not_modify_counts_or_session_status(self):
        subscription = self._make_active_subscription(self.member_b_id, total_sessions=2)
        pending_session = create_private_training_session_checkin(self.trainer_user, subscription["id"])
        before = get_private_training_subscription(subscription["id"])
        pending_before = get_private_training_pending_session(subscription["id"])

        save_private_training_todays_workout(self.trainer_user, subscription["id"], "Recovery")

        after = get_private_training_subscription(subscription["id"])
        pending_after = get_private_training_pending_session(subscription["id"])
        self.assertEqual(before["approved_count"], after["approved_count"])
        self.assertEqual(before["remaining_sessions"], after["remaining_sessions"])
        self.assertEqual(pending_before["status"], pending_after["status"])
        self.assertEqual(pending_session["status"], pending_after["status"])

    def test_15_cancelled_subscription_keeps_historical_workout(self):
        subscription = self._make_active_subscription(self.member_c_id)
        save_private_training_todays_workout(self.trainer_user, subscription["id"], "Legs")

        cancel_private_training_subscription(self.manager_user, subscription["id"])

        workout = get_private_training_daily_workout(subscription["id"], self._today())
        self.assertIsNotNone(workout)
        self.assertEqual(workout["workout_name"], "Legs")

    def test_16_completed_subscription_keeps_historical_workout(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=1)
        save_private_training_todays_workout(self.trainer_user, subscription["id"], "Upper")
        checkin = create_private_training_session_checkin(self.trainer_user, subscription["id"])
        approve_private_training_session(subscription["id"], checkin["id"], {"subscription_id": subscription["id"]})

        workout = get_private_training_daily_workout(subscription["id"], self._today())
        self.assertIsNotNone(workout)
        self.assertEqual(workout["workout_name"], "Upper")
        self.assertEqual(get_private_training_subscription(subscription["id"])["status"], "COMPLETED")

    def test_17_old_member_reject_endpoint_still_returns_404(self):
        subscription = self._make_active_subscription(self.member_e_id)
        portal_client, csrf, portal_url, raw_token = self._generate_portal(subscription["id"])
        checkin = create_private_training_session_checkin(self.trainer_user, subscription["id"])

        response = portal_client.post(
            f"/private-training/member/{raw_token}/sessions/{checkin['id']}/reject",
            data={
                "csrf_token": csrf,
                "rejection_reason": "Not needed",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertEqual(get_private_training_pending_session(subscription["id"])["status"], "PENDING_MEMBER_APPROVAL")

    def test_18_rejected_history_remains_hidden_from_member_portal(self):
        subscription = self._make_active_subscription(self.member_f_id)
        # Create a rejected session through the shared domain service.
        create_private_training_session_checkin(self.trainer_user, subscription["id"])
        pending = get_private_training_pending_session(subscription["id"])
        reject_private_training_session(
            subscription["id"],
            pending["id"],
            "Member requested a pause",
            {"subscription_id": subscription["id"]},
        )

        portal_client, _, portal_url, raw_token = self._generate_portal(subscription["id"])
        response = portal_client.get(urlparse(portal_url).path)
        html = response.data.decode()
        self.assertNotIn("REJECTED", html)
        self.assertNotIn("rejected_at", html.lower())
        self.assertNotIn("rejection_reason", html.lower())
