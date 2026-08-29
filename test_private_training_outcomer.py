import re
import unittest
from datetime import timedelta

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.private_training.services import (
    PrivateTrainingSubscriptionConflictError,
    PrivateTrainingNotFoundError,
    PrivateTrainingValidationError,
    approve_private_training_session,
    cancel_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_subscription,
    current_private_training_counts,
    generate_portal_token,
    get_private_training_pending_session,
    get_private_training_sessions,
    get_private_training_subscription,
    list_private_clients_for_trainer,
    resolve_portal_token,
    revoke_portal_token,
)


class PrivateTrainingOutcomerSupportTest(unittest.TestCase):
    manager_user_id = 996001
    trainer_user_id = 996002
    member_user_id = 996101

    def setUp(self):
        self._old_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        self.created_subscription_ids = []
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        self._upsert_users()
        self._upsert_members()

        self.manager_user = self._load_user(self.manager_user_id)
        self.trainer_user = self._load_user(self.trainer_user_id)
        self.member_user = self._load_user(self.member_user_id)

    def tearDown(self):
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf_enabled

    def _today(self):
        return get_cairo_date()

    def _date_str(self, delta_days):
        return (self._today() + timedelta(days=delta_days)).strftime("%Y-%m-%d")

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]
            sess["username"] = user["username"]

    def _upsert_users(self):
        users = [
            (self.manager_user_id, "pto_manager", "pto_manager@test.local", True, {"private_training_manage": True}),
            (self.trainer_user_id, "pto_trainer", "pto_trainer@test.local", True, {"private_training_trainer": True}),
            (self.member_user_id, "pto_member", "pto_member@test.local", True, {}),
        ]
        for user_id, username, email, is_approved, permissions in users:
            query_db(
                """
                INSERT INTO users (id, username, email, password, is_approved, permissions)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    username = EXCLUDED.username,
                    email = EXCLUDED.email,
                    password = EXCLUDED.password,
                    is_approved = EXCLUDED.is_approved,
                    permissions = EXCLUDED.permissions
                """,
                (user_id, username, email, "pwd", is_approved, Json(permissions)),
                commit=True,
            )

    def _upsert_members(self):
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
            (self.member_user_id, "Gym Member Alpha", "700100", self._date_str(-1), self._date_str(30)),
            commit=True,
        )

    def _cleanup_private_training(self):
        for subscription_id in list(self.created_subscription_ids):
            query_db("DELETE FROM private_training_portal_tokens WHERE subscription_id = %s", (subscription_id,), commit=True)
            query_db("DELETE FROM private_training_sessions WHERE subscription_id = %s", (subscription_id,), commit=True)
            query_db("DELETE FROM private_training_subscriptions WHERE id = %s", (subscription_id,), commit=True)
        self.created_subscription_ids.clear()

    def _cleanup_members(self):
        query_db("DELETE FROM members WHERE id = %s", (self.member_user_id,), commit=True)

    def _cleanup_users(self):
        query_db(
            "DELETE FROM users WHERE id IN (%s, %s, %s)",
            (self.manager_user_id, self.trainer_user_id, self.member_user_id),
            commit=True,
        )

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_member_subscription(self):
        result = create_private_training_subscription(
            self.manager_user,
            self.member_user_id,
            self.trainer_user_id,
            2,
            self._date_str(0),
            self._date_str(30),
        )
        subscription = result["subscription"]
        self.created_subscription_ids.append(subscription["id"])
        return subscription

    def _create_outcomer_subscription(self, *, phone="010-555-0101", name="Outcomer Alpha", total_sessions=2):
        result = create_private_training_subscription(
            self.manager_user,
            None,
            self.trainer_user_id,
            total_sessions,
            self._date_str(0),
            self._date_str(30),
            client_type="OUTCOMER",
            client_name=name,
            client_phone=phone,
        )
        subscription = result["subscription"]
        self.created_subscription_ids.append(subscription["id"])
        return subscription

    def _extract_generated_url(self, html):
        match = re.search(r'value="(https?://[^"]+/private-training/member/([A-Za-z0-9_-]+))"', html)
        self.assertIsNotNone(match, "Expected generated portal URL to be rendered")
        return match.group(1), match.group(2)

    def test_01_member_subscription_still_snapshots_gym_member_data(self):
        subscription = self._create_member_subscription()
        self.assertEqual(subscription["client_type"], "MEMBER")
        self.assertEqual(subscription["member_id"], self.member_user_id)
        self.assertEqual(subscription["client_name"], "Gym Member Alpha")
        self.assertEqual(subscription["client_phone"], "700100")
        self.assertEqual(subscription["member_name"], "Gym Member Alpha")
        self.assertEqual(subscription["member_phone"], "700100")

    def test_02_outcomer_subscription_creates_without_members_row(self):
        phone = "010-555-0101"
        subscription = self._create_outcomer_subscription(phone=phone)
        self.assertIsNone(subscription["member_id"])
        self.assertEqual(subscription["client_type"], "OUTCOMER")
        self.assertEqual(subscription["client_name"], "Outcomer Alpha")
        self.assertEqual(subscription["client_phone"], phone)
        self.assertIsNone(query_db("SELECT id FROM members WHERE phone = %s", (phone,), one=True))

    def test_03_outcomer_requires_name_and_phone(self):
        with self.assertRaises(PrivateTrainingValidationError):
            create_private_training_subscription(
                self.manager_user,
                None,
                self.trainer_user_id,
                2,
                self._date_str(0),
                self._date_str(30),
                client_type="OUTCOMER",
                client_name="",
                client_phone="0105550101",
            )
        with self.assertRaises(PrivateTrainingValidationError):
            create_private_training_subscription(
                self.manager_user,
                None,
                self.trainer_user_id,
                2,
                self._date_str(0),
                self._date_str(30),
                client_type="OUTCOMER",
                client_name="Outcomer Beta",
                client_phone="   ",
            )

    def test_04_outcomer_appears_in_subscription_list_and_detail(self):
        subscription = self._create_outcomer_subscription()
        self._login_as(self.manager_user)
        list_response = self.client.get("/private-training/subscriptions")
        self.assertEqual(list_response.status_code, 200)
        list_html = list_response.data.decode()
        self.assertIn("Outcomer Alpha", list_html)
        self.assertIn("OUTCOMER", list_html)
        self.assertIn("Private Only", list_html)

        detail_response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        self.assertEqual(detail_response.status_code, 200)
        detail_html = detail_response.data.decode()
        self.assertIn("Client Details", detail_html)
        self.assertIn("Outcomer Alpha", detail_html)
        self.assertIn("Private Only", detail_html)
        self.assertNotIn("Gym Details", detail_html)

    def test_05_trainer_sees_outcomer_and_can_check_in_with_workout(self):
        subscription = self._create_outcomer_subscription()
        self._login_as(self.trainer_user)
        response = self.client.get("/private-training/my-clients")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Outcomer Alpha", response.data.decode())

        session_row = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Leg Day")
        self.assertEqual(session_row["status"], "PENDING_MEMBER_APPROVAL")
        pending = get_private_training_pending_session(subscription["id"])
        self.assertIsNotNone(pending)
        self.assertEqual(pending["workout_name"], "Leg Day")

    def test_06_portal_works_for_outcomer_and_approval_updates_counts(self):
        subscription = self._create_outcomer_subscription()
        session_row = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Push Day")
        token_result = generate_portal_token(self.trainer_user, subscription["id"])
        raw_token = token_result["raw_token"]

        portal_response = self.client.get(f"/private-training/member/{raw_token}")
        self.assertEqual(portal_response.status_code, 200)
        portal_html = portal_response.data.decode()
        self.assertIn("Client Details", portal_html)
        self.assertIn("Outcomer Alpha", portal_html)
        self.assertIn("Private Only", portal_html)
        self.assertIn("Push Day", portal_html)

        approve_response = self.client.post(
            f"/private-training/member/{raw_token}/sessions/{session_row['id']}/approve",
            follow_redirects=True,
        )
        self.assertEqual(approve_response.status_code, 200)
        approved_html = approve_response.data.decode()
        self.assertIn("Push Day", approved_html)
        self.assertIn("APPROVED", approved_html)
        counts = current_private_training_counts(subscription["id"])
        self.assertEqual(counts["approved_count"], 1)
        self.assertEqual(counts["remaining_sessions"], 1)
        session_history = get_private_training_sessions(subscription["id"])
        self.assertEqual(session_history[0]["workout_name"], "Push Day")

    def test_07_portal_revoke_and_regenerate_still_work(self):
        subscription = self._create_outcomer_subscription()
        self._login_as(self.trainer_user)
        first_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        first_token = self._extract_generated_url(first_response.data.decode())[1]
        second_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        second_token = self._extract_generated_url(second_response.data.decode())[1]
        self.assertNotEqual(first_token, second_token)
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(first_token)
        resolved = resolve_portal_token(second_token)
        self.assertEqual(resolved["subscription"]["id"], subscription["id"])

        revoke_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token/revoke", follow_redirects=True)
        self.assertEqual(revoke_response.status_code, 200)
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(second_token)

    def test_08_duplicate_outcomer_phone_rejected_until_previous_subscription_is_no_longer_effective(self):
        first = self._create_outcomer_subscription(phone="010-555-0202")
        with self.assertRaises(PrivateTrainingSubscriptionConflictError):
            create_private_training_subscription(
                self.manager_user,
                None,
                self.trainer_user_id,
                2,
                self._date_str(0),
                self._date_str(30),
                client_type="OUTCOMER",
                client_name="Outcomer Alpha Two",
                client_phone="0105550202",
            )

        cancel_private_training_subscription(self.manager_user, first["id"])
        second = create_private_training_subscription(
            self.manager_user,
            None,
            self.trainer_user_id,
            2,
            self._date_str(0),
            self._date_str(30),
            client_type="OUTCOMER",
            client_name="Outcomer Alpha Two",
            client_phone="0105550202",
        )["subscription"]
        self.created_subscription_ids.append(second["id"])
        self.assertEqual(second["client_type"], "OUTCOMER")

    def test_09_outcomer_is_absent_from_normal_member_search(self):
        self._create_outcomer_subscription(phone="010-555-0303", name="Outcomer Searchless")
        self._login_as(self.manager_user)
        api_response = self.client.get("/api/search/members", query_string={"q": "Outcomer Searchless", "limit": 5})
        self.assertEqual(api_response.status_code, 200)
        self.assertEqual(api_response.get_json(), [])
        self.assertIsNone(query_db("SELECT id FROM members WHERE phone = %s", ("010-555-0303",), one=True))


if __name__ == "__main__":
    unittest.main()
