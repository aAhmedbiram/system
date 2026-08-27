import io
import re
import threading
import unittest
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
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
    approve_private_training_session,
    create_private_training_session_checkin,
    create_private_training_subscription,
    generate_portal_token,
    get_private_training_pending_session,
    get_private_training_subscription,
    reject_private_training_session,
    resolve_portal_token,
    revoke_portal_token,
)


class PrivateTrainingPhase1C1DTest(unittest.TestCase):
    manager_user_id = 970001
    trainer_user_id = 970002
    trainer_b_user_id = 970003
    super_admin_user_id = 970004
    viewer_user_id = 970005
    no_perm_user_id = 970006

    member_a_id = 980001
    member_b_id = 980002
    member_c_id = 980003
    member_d_id = 980004
    member_e_id = 980005
    member_f_id = 980006
    member_g_id = 980007
    member_h_id = 980008

    def setUp(self):
        self._old_testing = app.config.get("TESTING")
        self._old_csrf = app.config.get("WTF_CSRF_ENABLED")
        self._old_debug = app.debug
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
        self.super_admin_user = self._load_user(self.super_admin_user_id)
        self.viewer_user = self._load_user(self.viewer_user_id)
        self.no_perm_user = self._load_user(self.no_perm_user_id)

    def tearDown(self):
        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        app.config["TESTING"] = self._old_testing
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf
        app.debug = self._old_debug

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
        self.assertIsNotNone(match, "Expected csrf_token hidden input")
        return match.group(1)

    def _portal_url_from_html(self, html: str) -> tuple[str, str]:
        match = re.search(r'value="(https?://[^"]+/private-training/member/([A-Za-z0-9_-]+))"', html)
        self.assertIsNotNone(match, "Expected generated portal URL")
        return match.group(1), match.group(2)

    def _upsert_users(self):
        users = [
            (self.manager_user_id, "ptc_manager", {"private_training_manage": True}),
            (self.trainer_user_id, "ptc_trainer_a", {"private_training_trainer": True}),
            (self.trainer_b_user_id, "ptc_trainer_b", {"private_training_trainer": True}),
            (self.super_admin_user_id, "ptc_super_admin", {"super_admin": True}),
            (self.viewer_user_id, "ptc_viewer", {"private_training_view": True}),
            (self.no_perm_user_id, "ptc_no_perm", {}),
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
                self.member_g_id,
                self.member_h_id,
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
                (member_id, f"PTC Member {index}", f"9900{index:02d}", self._date_str(-1), self._date_str(30)),
                commit=True,
            )

    def _cleanup_private_training(self):
        query_db(
            """
            DELETE FROM private_training_portal_tokens
            WHERE subscription_id IN (
                SELECT id
                FROM private_training_subscriptions
                WHERE member_id BETWEEN 980001 AND 980008
                   OR trainer_user_id BETWEEN 970001 AND 970006
                   OR created_by_user_id BETWEEN 970001 AND 970006
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
                WHERE member_id BETWEEN 980001 AND 980008
                   OR trainer_user_id BETWEEN 970001 AND 970006
                   OR created_by_user_id BETWEEN 970001 AND 970006
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE member_id BETWEEN 980001 AND 980008
               OR trainer_user_id BETWEEN 970001 AND 970006
               OR created_by_user_id BETWEEN 970001 AND 970006
            """,
            commit=True,
        )

    def _cleanup_members(self):
        query_db("DELETE FROM members WHERE id BETWEEN 980001 AND 980008", commit=True)

    def _cleanup_users(self):
        query_db("DELETE FROM users WHERE id BETWEEN 970001 AND 970006", commit=True)

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_subscription(
        self,
        member_id,
        trainer_user_id,
        *,
        total_sessions=2,
        start_offset_days=0,
        expiry_offset_days=30,
        creator=None,
    ):
        creator = creator or self.manager_user
        result = create_private_training_subscription(
            creator,
            member_id,
            trainer_user_id,
            total_sessions,
            self._date_str(start_offset_days),
            self._date_str(expiry_offset_days),
        )
        return result["subscription"]

    def _make_active_subscription(self, member_id, *, trainer_user_id=None, total_sessions=2, creator=None):
        return self._create_subscription(
            member_id,
            trainer_user_id or self.trainer_user_id,
            total_sessions=total_sessions,
            start_offset_days=0,
            expiry_offset_days=30,
            creator=creator,
        )

    def _make_future_subscription(self, member_id, *, trainer_user_id=None, total_sessions=2):
        return self._create_subscription(
            member_id,
            trainer_user_id or self.trainer_user_id,
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

    def _cancel_subscription(self, subscription_id):
        query_db(
            "UPDATE private_training_subscriptions SET status = 'CANCELLED' WHERE id = %s",
            (subscription_id,),
            commit=True,
        )

    def _generate_portal(self, subscription_id, *, trainer_user=None):
        trainer_user = trainer_user or self.trainer_user
        client = app.test_client()
        self._login_as(client, trainer_user)
        detail_response = client.get(f"/private-training/subscriptions/{subscription_id}")
        csrf_token = self._csrf_from_html(detail_response.data.decode())
        response = client.post(
            f"/private-training/subscriptions/{subscription_id}/portal-token",
            data={"csrf_token": csrf_token},
        )
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        generated_url, raw_token = self._portal_url_from_html(html)
        return client, html, generated_url, raw_token

    def _open_detail(self, subscription_id, user):
        client = app.test_client()
        self._login_as(client, user)
        response = client.get(f"/private-training/subscriptions/{subscription_id}")
        return client, response

    def _portal_get(self, raw_token):
        return app.test_client().get(f"/private-training/member/{raw_token}")

    def _portal_post(self, raw_token, session_id, action, data=None, client=None, follow_redirects=False):
        client = client or app.test_client()
        payload = {"csrf_token": self._csrf_from_html(client.get(f"/private-training/member/{raw_token}").data.decode())}
        if data:
            payload.update(data)
        return client.post(
            f"/private-training/member/{raw_token}/sessions/{session_id}/{action}",
            data=payload,
            follow_redirects=follow_redirects,
        )

    def _trainer_checkin_post(self, client, subscription_id, csrf_token=None, workout_name="Workout", follow_redirects=True):
        if csrf_token is None:
            csrf_token = self._csrf_from_html(client.get(f"/private-training/subscriptions/{subscription_id}").data.decode())
        return client.post(
            f"/private-training/subscriptions/{subscription_id}/check-in",
            data={"csrf_token": csrf_token, "workout_name": workout_name},
            follow_redirects=follow_redirects,
        )

    def test_01_valid_token_opens_portal_and_displays_context(self):
        subscription = self._make_active_subscription(self.member_a_id)
        create_private_training_session_checkin(self.trainer_user, subscription["id"], "Chest")
        _, _, _, raw_token = self._generate_portal(subscription["id"])
        response = self._portal_get(raw_token)
        html = response.data.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Private Training Portal", html)
        self.assertIn("PTC Member 1", html)
        self.assertIn("PTC Trainer A", html)
        self.assertIn("Gym Details", html)
        self.assertIn("Private Training", html)
        self.assertIn("Pending Member Approval", html)
        self.assertIn("Workout: Chest", html)
        self.assertIn("Session History", html)
        self.assertIn("Approved At", html)
        self.assertIn("table-wrap", html)
        self.assertIn("Approved Sessions: 0", html)
        self.assertIn("Remaining Sessions: 2", html)
        self.assertIn('name="csrf_token"', html)
        self.assertIn("Approve Session", html)
        self.assertNotIn("Reject Session", html)
        self.assertNotIn("Rejected At", html)
        self.assertNotIn("Reason", html)
        self.assertNotIn("rejection_reason", html)

    def test_02_invalid_token_returns_404(self):
        response = self._portal_get("not-a-valid-token")
        self.assertEqual(response.status_code, 404)

    def test_03_revoked_token_returns_404(self):
        subscription = self._make_active_subscription(self.member_b_id)
        _, _, _, raw_token = self._generate_portal(subscription["id"])
        revoke_portal_token(self.trainer_user, subscription["id"])
        response = self._portal_get(raw_token)
        self.assertEqual(response.status_code, 404)

    def test_04_regenerated_old_token_returns_404_and_new_token_works(self):
        subscription = self._make_active_subscription(self.member_c_id)
        _, _, _, first_token = self._generate_portal(subscription["id"])
        _, _, _, second_token = self._generate_portal(subscription["id"])
        self.assertNotEqual(first_token, second_token)
        self.assertEqual(self._portal_get(first_token).status_code, 404)
        self.assertEqual(self._portal_get(second_token).status_code, 200)

    def test_05_ended_subscription_returns_410(self):
        expired = self._make_active_subscription(self.member_d_id)
        _, _, _, raw_token = self._generate_portal(expired["id"])
        self._expire_subscription(expired["id"])
        response = self._portal_get(raw_token)
        self.assertEqual(response.status_code, 410)
        self.assertIn("no longer available", response.data.decode().lower())

        completed = self._make_active_subscription(self.member_e_id, total_sessions=1)
        _, _, _, completed_token = self._generate_portal(completed["id"])
        pending = create_private_training_session_checkin(self.trainer_user, completed["id"], "Upper Body")
        approve_private_training_session(completed["id"], pending["id"], {"subscription_id": completed["id"]})
        self.assertEqual(self._portal_get(completed_token).status_code, 410)

        cancelled = self._make_active_subscription(self.member_f_id)
        _, _, _, cancelled_token = self._generate_portal(cancelled["id"])
        self._cancel_subscription(cancelled["id"])
        self.assertEqual(self._portal_get(cancelled_token).status_code, 410)

    def test_06_portal_headers_and_csrf_session_are_present(self):
        subscription = self._make_active_subscription(self.member_g_id)
        _, _, _, raw_token = self._generate_portal(subscription["id"])
        response = self._portal_get(raw_token)
        self.assertEqual(response.headers.get("Cache-Control"), "no-store, private")
        self.assertEqual(response.headers.get("Pragma"), "no-cache")
        self.assertEqual(response.headers.get("X-Robots-Tag"), "noindex, nofollow")
        self.assertEqual(response.headers.get("Referrer-Policy"), "no-referrer")
        self.assertIn('name="csrf-token"', response.data.decode())

    def test_07_raw_token_redacted_from_request_and_error_logging(self):
        subscription = self._make_active_subscription(self.member_h_id)
        _, _, _, raw_token = self._generate_portal(subscription["id"])

        with patch.object(app.logger, "info") as mock_info:
            self._portal_get(raw_token)
        logged = " ".join(str(call.args[0]) for call in mock_info.call_args_list)
        self.assertIn("[REDACTED]", logged)
        self.assertNotIn(raw_token, logged)

        old_debug = app.debug
        app.debug = True
        try:
            buffer = io.StringIO()
            with patch("system_app.private_training.public_routes.resolve_portal_token", side_effect=RuntimeError("boom")):
                with redirect_stdout(buffer):
                    response = self._portal_get(raw_token)
            self.assertEqual(response.status_code, 500)
            output = buffer.getvalue()
            self.assertIn("[REDACTED]", output)
            self.assertNotIn(raw_token, output)
        finally:
            app.debug = old_debug

    def test_08_portal_url_generation_and_one_time_display(self):
        subscription = self._make_active_subscription(self.member_a_id)
        _, html, generated_url, raw_token = self._generate_portal(subscription["id"])
        self.assertTrue(generated_url.startswith("http"))
        self.assertIn("/private-training/member/", generated_url)
        self.assertIn(raw_token, generated_url)
        token_row = query_db(
            """
            SELECT token_hash
            FROM private_training_portal_tokens
            WHERE subscription_id = %s AND revoked_at IS NULL
            ORDER BY id DESC
            LIMIT 1
            """,
            (subscription["id"],),
            one=True,
        )
        self.assertEqual(len(token_row["token_hash"]), 64)
        self.assertNotEqual(token_row["token_hash"], raw_token)
        detail_response = self._open_detail(subscription["id"], self.trainer_user)[1]
        self.assertNotIn(raw_token, detail_response.data.decode())
        self.assertIn("Active link exists", detail_response.data.decode())

    def test_09_manager_detail_is_read_only_for_tokens(self):
        subscription = self._make_active_subscription(self.member_b_id)
        _, response = self._open_detail(subscription["id"], self.manager_user)
        html = response.data.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Private Training Subscription", html)
        self.assertNotIn("Generate Link", html)
        self.assertNotIn("Regenerate Link", html)
        self.assertNotIn("Revoke Link", html)

    def test_10_trainer_and_super_admin_token_controls(self):
        subscription = self._make_active_subscription(self.member_c_id)
        _, response = self._open_detail(subscription["id"], self.trainer_user)
        html = response.data.decode()
        self.assertEqual(response.status_code, 200)
        self.assertIn("Generate Link", html)
        self.assertIn("Revoke Link", html)

        _, super_admin_response = self._open_detail(subscription["id"], self.super_admin_user)
        super_admin_html = super_admin_response.data.decode()
        self.assertEqual(super_admin_response.status_code, 200)
        self.assertIn("Generate Link", super_admin_html)
        self.assertIn("Revoke Link", super_admin_html)
        self.assertIn("Private Training Subscription", super_admin_html)

    def test_11_trainer_selector_requires_explicit_permission_and_create_validation(self):
        client = app.test_client()
        self._login_as(client, self.manager_user)
        create_page = client.get("/private-training/subscriptions/new")
        self.assertEqual(create_page.status_code, 200)
        create_html = create_page.data.decode()
        self.assertIn("ptc_trainer_a", create_html)
        self.assertNotIn("ptc_super_admin", create_html)

        csrf = self._csrf_from_html(create_html)
        invalid_member_response = client.post(
            "/private-training/subscriptions",
            data={
                "csrf_token": csrf,
                "member_id": "999999",
                "trainer_user_id": str(self.trainer_user_id),
                "total_sessions": "2",
                "private_start_date": self._date_str(0),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(invalid_member_response.status_code, 400)

        invalid_trainer_response = client.post(
            "/private-training/subscriptions",
            data={
                "csrf_token": csrf,
                "member_id": str(self.member_a_id),
                "trainer_user_id": "999998",
                "total_sessions": "2",
                "private_start_date": self._date_str(0),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(invalid_trainer_response.status_code, 400)

        super_admin_as_trainer = client.post(
            "/private-training/subscriptions",
            data={
                "csrf_token": csrf,
                "member_id": str(self.member_a_id),
                "trainer_user_id": str(self.super_admin_user_id),
                "total_sessions": "2",
                "private_start_date": self._date_str(0),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(super_admin_as_trainer.status_code, 400)

        valid = client.post(
            "/private-training/subscriptions",
            data={
                "csrf_token": csrf,
                "member_id": str(self.member_a_id),
                "trainer_user_id": str(self.trainer_user_id),
                "total_sessions": "2",
                "private_start_date": self._date_str(0),
                "private_expiry_date": self._date_str(30),
            },
            follow_redirects=True,
        )
        self.assertEqual(valid.status_code, 200)

        duplicate = client.post(
            "/private-training/subscriptions",
            data={
                "csrf_token": csrf,
                "member_id": str(self.member_a_id),
                "trainer_user_id": str(self.trainer_user_id),
                "total_sessions": "2",
                "private_start_date": self._date_str(0),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_12_create_page_rejects_no_permission_users(self):
        client = app.test_client()
        self._login_as(client, self.no_perm_user)
        response = client.get("/private-training/subscriptions/new")
        self.assertEqual(response.status_code, 302)

    def test_13_checkin_creates_pending_and_portal_syncs(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=2)
        trainer_client = app.test_client()
        self._login_as(trainer_client, self.trainer_user)
        response = self._trainer_checkin_post(trainer_client, subscription["id"], workout_name="Leg Day")
        self.assertEqual(response.status_code, 200)
        self.assertIn("Waiting for Member Approval", response.data.decode())
        self.assertIn("Workout: Leg Day", response.data.decode())
        pending = get_private_training_pending_session(subscription["id"])
        self.assertIsNotNone(pending)
        self.assertEqual(pending["workout_name"], "Leg Day")

        _, _, _, raw_token = self._generate_portal(subscription["id"])
        portal_html = self._portal_get(raw_token).data.decode()
        self.assertIn("Pending Member Approval", portal_html)
        self.assertIn("Workout: Leg Day", portal_html)
        self.assertIn("PTC Trainer A", portal_html)
        self.assertIn("Approve Session", portal_html)
        self.assertNotIn("Reject Session", portal_html)
        self.assertNotIn("Rejected At", portal_html)
        self.assertNotIn("Reason", portal_html)
        self.assertNotIn("rejection_reason", portal_html)

    def test_14_checkin_ui_blocks_future_expired_cancelled_completed_and_zero_remaining(self):
        trainer_client = app.test_client()
        self._login_as(trainer_client, self.trainer_user)

        future = self._make_future_subscription(self.member_e_id)
        future_html = trainer_client.get(f"/private-training/subscriptions/{future['id']}").data.decode()
        self.assertNotIn("Check-In Session", future_html)
        self.assertIn("not started yet", future_html)

        expired = self._make_active_subscription(self.member_f_id)
        self._expire_subscription(expired["id"])
        expired_html = trainer_client.get(f"/private-training/subscriptions/{expired['id']}").data.decode()
        self.assertNotIn("Check-In Session", expired_html)

        cancelled = self._make_active_subscription(self.member_g_id)
        self._cancel_subscription(cancelled["id"])
        cancelled_html = trainer_client.get(f"/private-training/subscriptions/{cancelled['id']}").data.decode()
        self.assertNotIn("Check-In Session", cancelled_html)

        completed = self._make_active_subscription(self.member_h_id, total_sessions=1)
        pending = create_private_training_session_checkin(self.trainer_user, completed["id"], "Full Body")
        approve_private_training_session(completed["id"], pending["id"], {"subscription_id": completed["id"]})
        completed_html = trainer_client.get(f"/private-training/subscriptions/{completed['id']}").data.decode()
        self.assertNotIn("Check-In Session", completed_html)
        self.assertIn("COMPLETED", completed_html)

    def test_15_checkin_requires_csrf_and_ownership(self):
        subscription = self._make_active_subscription(self.member_a_id)

        trainer_client = app.test_client()
        self._login_as(trainer_client, self.trainer_user)
        response = trainer_client.post(f"/private-training/subscriptions/{subscription['id']}/check-in", data={})
        self.assertEqual(response.status_code, 400)

        wrong_trainer_client = app.test_client()
        self._login_as(wrong_trainer_client, self.trainer_b_user)
        wrong_csrf = self._csrf_from_html(wrong_trainer_client.get("/private-training/my-clients").data.decode())
        response = wrong_trainer_client.post(
            f"/private-training/subscriptions/{subscription['id']}/check-in",
            data={"csrf_token": wrong_csrf},
            follow_redirects=True,
        )
        self.assertIsNone(get_private_training_pending_session(subscription["id"]))
        self.assertIn("My Private Clients", response.data.decode())

        manager_client = app.test_client()
        self._login_as(manager_client, self.manager_user)
        manager_csrf = self._csrf_from_html(manager_client.get(f"/private-training/subscriptions/{subscription['id']}").data.decode())
        response = manager_client.post(
            f"/private-training/subscriptions/{subscription['id']}/check-in",
            data={"csrf_token": manager_csrf},
            follow_redirects=True,
        )
        self.assertIsNone(get_private_training_pending_session(subscription["id"]))
        self.assertIn("Private Training Subscription", response.data.decode())

        anonymous_client = app.test_client()
        response = anonymous_client.post(f"/private-training/subscriptions/{subscription['id']}/check-in", data={})
        self.assertEqual(response.status_code, 302)

    def test_16_public_approve_requires_csrf_and_reject_url_is_unavailable(self):
        subscription = self._make_active_subscription(self.member_b_id)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Back Day")
        _, _, _, raw_token = self._generate_portal(subscription["id"])

        approve_response = app.test_client().post(
            f"/private-training/member/{raw_token}/sessions/{pending['id']}/approve",
            data={},
        )
        self.assertEqual(approve_response.status_code, 400)

        reject_response = app.test_client().post(
            f"/private-training/member/{raw_token}/sessions/{pending['id']}/reject",
            data={},
        )
        self.assertEqual(reject_response.status_code, 404)
        self.assertEqual(get_private_training_pending_session(subscription["id"])["id"], pending["id"])

    def test_17_approval_is_idempotent_and_final_approval_completes_subscription(self):
        subscription = self._make_active_subscription(self.member_c_id, total_sessions=1)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Push Day")
        first = approve_private_training_session(subscription["id"], pending["id"], {"subscription_id": subscription["id"]})
        self.assertEqual(first["outcome"], "approved")
        second = approve_private_training_session(subscription["id"], pending["id"], {"subscription_id": subscription["id"]})
        self.assertEqual(second["outcome"], "already_approved")
        subscription_row = get_private_training_subscription(subscription["id"])
        self.assertEqual(subscription_row["effective_status"], "COMPLETED")
        self.assertEqual(subscription_row["approved_count"], 1)
        self.assertEqual(subscription_row["remaining_sessions"], 0)

    def test_18_rejection_requires_reason_and_reopens_checkin(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=2)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Leg Day")
        with self.assertRaises(ValueError):
            reject_private_training_session(subscription["id"], pending["id"], "   ", {"subscription_id": subscription["id"]})

        result = reject_private_training_session(
            subscription["id"],
            pending["id"],
            "Trainer needs to reschedule",
            {"subscription_id": subscription["id"]},
        )
        self.assertEqual(result["outcome"], "rejected")
        session_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (pending["id"],), one=True)
        self.assertEqual(session_row["status"], "REJECTED")
        self.assertEqual(session_row["rejection_reason"], "Trainer needs to reschedule")
        subscription_row = get_private_training_subscription(subscription["id"])
        self.assertEqual(subscription_row["approved_count"], 0)
        self.assertEqual(subscription_row["remaining_sessions"], 2)
        repeated = reject_private_training_session(
            subscription["id"],
            pending["id"],
            "Trainer needs to reschedule",
            {"subscription_id": subscription["id"]},
        )
        self.assertEqual(repeated["outcome"], "already_rejected")

        _, _, _, raw_token = self._generate_portal(subscription["id"])
        portal_html = self._portal_get(raw_token).data.decode()
        self.assertNotIn("REJECTED", portal_html)
        self.assertNotIn("Rejected At", portal_html)
        self.assertNotIn("Reason", portal_html)
        self.assertNotIn("rejection_reason", portal_html)
        self.assertIn("No session history yet.", portal_html)

        second = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Arms Day")
        self.assertEqual(second["status"], "PENDING_MEMBER_APPROVAL")

    def test_19_wrong_token_cannot_access_other_subscription_session(self):
        sub_a = self._make_active_subscription(self.member_e_id)
        sub_b = self._make_active_subscription(self.member_f_id)
        pending = create_private_training_session_checkin(self.trainer_user, sub_a["id"], "Push Pull")
        _, _, _, token_b = self._generate_portal(sub_b["id"])
        client = app.test_client()
        csrf = self._csrf_from_html(client.get(f"/private-training/member/{token_b}").data.decode())
        response = client.post(
            f"/private-training/member/{token_b}/sessions/{pending['id']}/approve",
            data={"csrf_token": csrf},
        )
        self.assertEqual(response.status_code, 404)

    def test_20_concurrent_checkin_and_approval_races_are_safe(self):
        subscription = self._make_active_subscription(self.member_g_id, total_sessions=2)
        barrier = threading.Barrier(2)
        results = []

        def do_checkin():
            barrier.wait()
            try:
                results.append(create_private_training_session_checkin(self.trainer_user, subscription["id"], "Workout Race"))
            except Exception as exc:  # noqa: BLE001
                results.append(exc)

        threads = [threading.Thread(target=do_checkin) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        pending_rows = query_db(
            """
            SELECT COUNT(*) AS count
            FROM private_training_sessions
            WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL'
            """,
            (subscription["id"],),
            one=True,
        )
        self.assertEqual(pending_rows["count"], 1)

        pending = get_private_training_pending_session(subscription["id"])
        barrier = threading.Barrier(2)
        approval_results = []

        def do_approve():
            barrier.wait()
            try:
                approval_results.append(approve_private_training_session(subscription["id"], pending["id"], {"subscription_id": subscription["id"]}))
            except Exception as exc:  # noqa: BLE001
                approval_results.append(exc)

        threads = [threading.Thread(target=do_approve) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        subscription_row = get_private_training_subscription(subscription["id"])
        self.assertEqual(subscription_row["approved_count"], 1)
        self.assertEqual(subscription_row["remaining_sessions"], 1)
        self.assertEqual(subscription_row["effective_status"], "ACTIVE")

    def test_21_reject_then_checkin_again_and_approve_reject_race(self):
        subscription = self._make_active_subscription(self.member_h_id, total_sessions=2)
        pending = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Recovery")
        reject_private_training_session(
            subscription["id"],
            pending["id"],
            "Trainer needs to reschedule",
            {"subscription_id": subscription["id"]},
        )
        second = create_private_training_session_checkin(self.trainer_user, subscription["id"], "Mobility")
        self.assertEqual(second["status"], "PENDING_MEMBER_APPROVAL")

        results = []
        barrier = threading.Barrier(2)

        def do_approve():
            barrier.wait()
            try:
                results.append(approve_private_training_session(subscription["id"], second["id"], {"subscription_id": subscription["id"]}))
            except Exception as exc:  # noqa: BLE001
                results.append(exc)

        def do_reject():
            barrier.wait()
            try:
                results.append(reject_private_training_session(subscription["id"], second["id"], "Not ready", {"subscription_id": subscription["id"]}))
            except Exception as exc:  # noqa: BLE001
                results.append(exc)

        threads = [threading.Thread(target=do_approve), threading.Thread(target=do_reject)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        session_row = query_db("SELECT * FROM private_training_sessions WHERE id = %s", (second["id"],), one=True)
        self.assertIn(session_row["status"], ("APPROVED", "REJECTED"))


if __name__ == "__main__":
    unittest.main()
