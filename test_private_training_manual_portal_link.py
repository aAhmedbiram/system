"""End-to-end regression tests for manual Private Training approval link generation and public access."""

import hashlib
import re
import unittest
from datetime import timedelta

from psycopg2.extras import Json

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.private_training.queries import ensure_private_training_tables
from system_app.private_training.services import (
    create_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_checkin_invitation,
    generate_portal_token,
    get_private_training_subscription,
    get_private_training_pending_session,
    list_private_training_sessions,
)


class PrivateTrainingManualPortalLinkTests(unittest.TestCase):
    manager_user_id = 998001
    trainer_user_id = 998002
    other_trainer_user_id = 998003
    member_id = 998101

    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        app.config["PRIVATE_TRAINING_WHATSAPP_CHECKIN_ENABLED"] = True
        app.config["PRIVATE_TRAINING_PORTAL_TOKEN_SIGNING_KEY"] = "x" * 32
        self.client = app.test_client()

        ensure_private_training_tables()
        self._cleanup()
        self._upsert_fixtures()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        query_db(
            "DELETE FROM private_training_checkin_operations WHERE user_id IN (%s, %s, %s)",
            (self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id),
            commit=True,
        )
        query_db(
            "DELETE FROM private_training_portal_tokens WHERE created_by_user_id IN (%s, %s, %s)",
            (self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id),
            commit=True,
        )
        query_db(
            "DELETE FROM private_training_sessions WHERE trainer_user_id IN (%s, %s, %s)",
            (self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id),
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE trainer_user_id IN (%s, %s, %s)
               OR created_by_user_id IN (%s, %s, %s)
            """,
            (
                self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id,
                self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id,
            ),
            commit=True,
        )
        query_db("DELETE FROM members WHERE id = %s", (self.member_id,), commit=True)
        query_db("DELETE FROM users WHERE id IN (%s, %s, %s)", (self.manager_user_id, self.trainer_user_id, self.other_trainer_user_id), commit=True)

    def _upsert_fixtures(self):
        query_db(
            """
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
                (%s, 'manual_manager', 'manager_manual@test.local', 'pass', TRUE, %s),
                (%s, 'manual_trainer', 'trainer_manual@test.local', 'pass', TRUE, %s),
                (%s, 'other_trainer', 'other_trainer_manual@test.local', 'pass', TRUE, %s)
            """,
            (
                self.manager_user_id, Json({"private_training_manage": True}),
                self.trainer_user_id, Json({"private_training_trainer": True}),
                self.other_trainer_user_id, Json({"private_training_trainer": True}),
            ),
            commit=True,
        )
        today = get_cairo_date()
        query_db(
            """
            INSERT INTO members (id, name, phone, membership_status, starting_date, end_date)
            VALUES (%s, 'Manual Test Member', '01012345678', 'ACTIVE', %s, %s)
            """,
            (self.member_id, today - timedelta(days=1), today + timedelta(days=30)),
            commit=True,
        )
        self.manager_user = query_db("SELECT id, username, is_approved, permissions FROM users WHERE id = %s", (self.manager_user_id,), one=True)
        self.trainer_user = query_db("SELECT id, username, is_approved, permissions FROM users WHERE id = %s", (self.trainer_user_id,), one=True)
        self.other_trainer_user = query_db("SELECT id, username, is_approved, permissions FROM users WHERE id = %s", (self.other_trainer_user_id,), one=True)

    def _login_as(self, user):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user["id"]
            sess["username"] = user["username"]
            sess["is_approved"] = True
            sess["permissions"] = dict(user["permissions"])

    def _create_subscription(self):
        today = get_cairo_date()
        res = create_private_training_subscription(
            self.manager_user,
            self.member_id,
            self.trainer_user_id,
            5,
            today.isoformat(),
            (today + timedelta(days=30)).isoformat(),
            client_type="MEMBER",
        )
        return res["subscription"]

    def _extract_portal_url_and_token(self, html: str):
        match = re.search(r'id="portal-link"[^>]*value="([^"]+)"', html)
        self.assertIsNotNone(match, "portal-link input should be present in response")
        url = match.group(1)
        raw_token = url.split("/member/")[-1]
        return url, raw_token

    def test_A_manual_link_happy_path(self):
        sub = self._create_subscription()
        session_row = create_private_training_session_checkin(self.trainer_user, sub["id"], "Hypertrophy Push")
        
        self._login_as(self.trainer_user)
        response = self.client.post(f"/private-training/subscriptions/{sub['id']}/portal-token")
        self.assertEqual(response.status_code, 200)
        
        url, raw_token = self._extract_portal_url_and_token(response.data.decode())
        
        # Verify token DB row
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        token_row = query_db("SELECT * FROM private_training_portal_tokens WHERE token_hash = %s", (token_hash,), one=True)
        self.assertIsNotNone(token_row)
        self.assertEqual(token_row["subscription_id"], sub["id"])
        self.assertEqual(token_row["session_id"], session_row["id"])
        self.assertIsNone(token_row["revoked_at"])
        
        # Logged out client opens the exact extracted URL
        public_client = app.test_client()
        portal_res = public_client.get(f"/private-training/member/{raw_token}")
        self.assertEqual(portal_res.status_code, 200)
        portal_html = portal_res.data.decode()
        self.assertIn("Hypertrophy Push", portal_html)
        self.assertIn("Manual Test Member", portal_html)
        self.assertIn("Pending Member Approval", portal_html)

    def test_B_approval_path_via_manual_token(self):
        sub = self._create_subscription()
        session_row = create_private_training_session_checkin(self.trainer_user, sub["id"], "Pull Day")
        
        self._login_as(self.trainer_user)
        gen_res = self.client.post(f"/private-training/subscriptions/{sub['id']}/portal-token")
        _, raw_token = self._extract_portal_url_and_token(gen_res.data.decode())
        
        # Public approval submission
        public_client = app.test_client()
        approve_res = public_client.post(
            f"/private-training/member/{raw_token}/sessions/{session_row['id']}/approve",
            follow_redirects=True,
        )
        self.assertEqual(approve_res.status_code, 200)
        approved_html = approve_res.data.decode()
        self.assertIn("APPROVED", approved_html)
        self.assertIn("Session approved successfully.", approved_html)
        
        # Verify counts in DB
        updated_sub = get_private_training_subscription(sub["id"])
        self.assertEqual(updated_sub["approved_count"], 1)
        self.assertEqual(updated_sub["remaining_sessions"], 4)
        self.assertEqual(updated_sub["pending_count"], 0)

    def test_C_regeneration_revokes_old_and_activates_newest(self):
        sub = self._create_subscription()
        session_row = create_private_training_session_checkin(self.trainer_user, sub["id"], "Leg Day")
        
        self._login_as(self.trainer_user)
        first_gen = self.client.post(f"/private-training/subscriptions/{sub['id']}/portal-token")
        _, first_raw_token = self._extract_portal_url_and_token(first_gen.data.decode())
        
        second_gen = self.client.post(f"/private-training/subscriptions/{sub['id']}/portal-token")
        _, second_raw_token = self._extract_portal_url_and_token(second_gen.data.decode())
        self.assertNotEqual(first_raw_token, second_raw_token)
        
        public_client = app.test_client()
        # Old exact URL returns 404
        old_res = public_client.get(f"/private-training/member/{first_raw_token}")
        self.assertEqual(old_res.status_code, 404)
        
        # Newest exact URL returns 200
        new_res = public_client.get(f"/private-training/member/{second_raw_token}")
        self.assertEqual(new_res.status_code, 200)
        self.assertIn("Leg Day", new_res.data.decode())

    def test_D_no_pending_session_behavior(self):
        sub = self._create_subscription()
        self._login_as(self.trainer_user)
        
        # GET page check UI button
        detail_res = self.client.get(f"/private-training/subscriptions/{sub['id']}")
        self.assertEqual(detail_res.status_code, 200)
        html = detail_res.data.decode()
        self.assertNotIn("Generate Link", html)
        self.assertIn("No session is currently waiting for member approval.", html)
        
        # POST manual route when no pending session exists
        post_res = self.client.post(
            f"/private-training/subscriptions/{sub['id']}/portal-token",
            follow_redirects=True,
        )
        self.assertEqual(post_res.status_code, 200)
        post_html = post_res.data.decode()
        self.assertIn("No session is currently waiting for member approval.", post_html)
        
        tokens = query_db("SELECT * FROM private_training_portal_tokens WHERE subscription_id = %s", (sub['id'],))
        self.assertEqual(len(tokens), 0)

    def test_E_security_and_authorization(self):
        sub = self._create_subscription()
        session_row = create_private_training_session_checkin(self.trainer_user, sub["id"], "Core Day")
        
        # Unauthorized trainer cannot generate link
        self._login_as(self.other_trainer_user)
        forbidden_res = self.client.post(
            f"/private-training/subscriptions/{sub['id']}/portal-token",
            follow_redirects=True,
        )
        self.assertIn("You cannot access that private training subscription.", forbidden_res.data.decode())
        
        # Authorized trainer generates link
        self._login_as(self.trainer_user)
        gen_res = self.client.post(f"/private-training/subscriptions/{sub['id']}/portal-token")
        _, raw_token = self._extract_portal_url_and_token(gen_res.data.decode())
        
        # Assert raw token is not stored in plain text anywhere in DB
        stored_tokens = query_db("SELECT * FROM private_training_portal_tokens WHERE subscription_id = %s", (sub['id'],))
        for row in stored_tokens:
            self.assertNotIn(raw_token, str(row.values()))

    def test_F_regression_checkin_and_whatsapp_flow(self):
        sub = self._create_subscription()
        self._login_as(self.trainer_user)
        
        inv = create_private_training_checkin_invitation(
            self.trainer_user, sub['id'], "Full Body", "22222222-2222-4222-8222-222222222222", "x" * 32
        )
        raw_token = inv["raw_token"]
        self.assertEqual(inv["session"]["workout_name"], "Full Body")
        
        public_client = app.test_client()
        auto_url_res = public_client.get(f"/private-training/member/{raw_token}")
        self.assertEqual(auto_url_res.status_code, 200)
        self.assertIn("Full Body", auto_url_res.data.decode())


if __name__ == "__main__":
    unittest.main()
