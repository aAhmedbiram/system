import unittest

from psycopg2.extras import Json
from werkzeug.datastructures import MultiDict
from werkzeug.security import generate_password_hash

from system_app.app import app
from system_app.queries import query_db


class TestLoginLandingPhase1(unittest.TestCase):
    unapproved_user_id = 970001
    trainer_user_id = 970002
    manager_user_id = 970003
    viewer_user_id = 970004
    ordinary_user_id = 970005
    super_user_id = 970006
    rino_user_id = 970007

    def setUp(self):
        self._old_testing = app.config.get("TESTING")
        self._old_csrf = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        self._cleanup_users()
        self._upsert_users()
        self._apply_permissions_via_admin_ui()
        self.unapproved_user = self._load_user(self.unapproved_user_id)
        self.trainer_user = self._load_user(self.trainer_user_id)
        self.manager_user = self._load_user(self.manager_user_id)
        self.viewer_user = self._load_user(self.viewer_user_id)
        self.ordinary_user = self._load_user(self.ordinary_user_id)
        self.super_user = self._load_user(self.super_user_id)
        self.rino_user = self._load_user(self.rino_user_id)

    def tearDown(self):
        self._cleanup_users()
        app.config["TESTING"] = self._old_testing
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf

    def _cleanup_users(self):
        query_db(
            "DELETE FROM users WHERE id IN (970001, 970002, 970003, 970004, 970005, 970006, 970007)",
            commit=True,
        )

    def _upsert_users(self):
        users = [
            (self.unapproved_user_id, "pt_pending_login", False, {}),
            (self.trainer_user_id, "pt_login_trainer", True, {}),
            (self.manager_user_id, "pt_login_manager", True, {}),
            (self.viewer_user_id, "pt_login_viewer", True, {}),
            (self.ordinary_user_id, "pt_login_ordinary", True, {}),
            (self.super_user_id, "pt_login_super", True, {"super_admin": True}),
            (self.rino_user_id, "rino", True, {}),
        ]
        for user_id, username, is_approved, permissions in users:
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
                (
                    user_id,
                    username,
                    f"{username}@test.local",
                    generate_password_hash("pw123"),
                    is_approved,
                    Json(permissions),
                ),
                commit=True,
            )

    def _login_as_rino(self):
        response = self._login("rino")
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/home")
            or response.location.endswith("/index")
        )

    def _apply_permissions_via_admin_ui(self):
        permission_sets = [
            (self.trainer_user_id, True, ["private_training_trainer"]),
            (self.manager_user_id, True, ["private_training_manage"]),
            (self.viewer_user_id, True, ["private_training_view"]),
            (self.ordinary_user_id, True, ["attendance"]),
            (self.unapproved_user_id, False, []),
        ]
        self._login_as_rino()
        for user_id, is_approved, perms in permission_sets:
            payload = MultiDict([("user_id", str(user_id))])
            if is_approved:
                payload.add("is_approved", "on")
            for perm in perms:
                payload.add("perms", perm)
            response = self.client.post("/user_permissions", data=payload, follow_redirects=False)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/user_permissions", response.location)
        self.client.get("/logout", follow_redirects=False)

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _login(self, username, password="pw123"):
        return self.client.post(
            "/login",
            data={"username": username, "password": password},
            follow_redirects=False,
        )

    def test_01_unapproved_login_redirects_to_pending_approval(self):
        response = self._login(self.unapproved_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertIn("/pending-approval", response.location)

    def test_01b_trainer_permission_is_persisted_via_admin_ui(self):
        trainer = self._load_user(self.trainer_user_id)
        manager = self._load_user(self.manager_user_id)
        viewer = self._load_user(self.viewer_user_id)
        self.assertTrue(trainer["is_approved"])
        self.assertTrue(trainer["permissions"].get("private_training_trainer"))
        self.assertTrue(manager["permissions"].get("private_training_manage"))
        self.assertTrue(viewer["permissions"].get("private_training_view"))

    def test_02_unapproved_user_cannot_open_home(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.unapproved_user_id
            sess["username"] = self.unapproved_user["username"]
        response = self.client.get("/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/pending-approval", response.location)

    def test_03_unapproved_user_cannot_open_attendance(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.unapproved_user_id
            sess["username"] = self.unapproved_user["username"]
        response = self.client.get("/attendance_table", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/pending-approval", response.location)

    def test_04_unapproved_user_cannot_open_private_training(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.unapproved_user_id
            sess["username"] = self.unapproved_user["username"]
        response = self.client.get("/private-training/", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/pending-approval", response.location)

    def test_05_trainer_lands_on_my_clients_and_can_open_it_directly(self):
        response = self._login(self.trainer_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertIn("/private-training/my-clients", response.location)

        with self.client.session_transaction() as sess:
            sess["user_id"] = self.trainer_user_id
            sess["username"] = self.trainer_user["username"]
        direct = self.client.get("/private-training/my-clients")
        self.assertEqual(direct.status_code, 200)
        html = direct.data.decode()
        self.assertIn("My Private Clients", html)
        self.assertIn("Logout", html)

    def test_05b_trainer_only_cannot_use_attendance_home_or_index(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.trainer_user_id
            sess["username"] = self.trainer_user["username"]

        attendance = self.client.get("/attendance_table", follow_redirects=False)
        self.assertEqual(attendance.status_code, 302)
        self.assertIn("/private-training/my-clients", attendance.location)

        home = self.client.get("/home", follow_redirects=True)
        self.assertEqual(home.status_code, 200)
        self.assertIn("My Private Clients", home.data.decode())
        self.assertNotIn("Attendance Table", home.data.decode())

    def test_06_manager_lands_on_subscription_list(self):
        response = self._login(self.manager_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertIn("/private-training/subscriptions", response.location)

    def test_06b_private_training_card_is_rendered_below_monthly_statistics(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.super_user_id
            sess["username"] = self.super_user["username"]
        response = self.client.get("/home")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        stats_index = html.index("Monthly Statistics")
        private_training_index = html.index("🏋️ Private Training")
        self.assertGreater(private_training_index, stats_index)
        self.assertIn("Open Private Training", html)

    def test_07_view_user_lands_on_subscription_list(self):
        response = self._login(self.viewer_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertIn("/private-training/subscriptions", response.location)

    def test_08_ordinary_user_keeps_existing_standard_landing(self):
        response = self._login(self.ordinary_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertIn("/attendance_table", response.location)

    def test_08b_user_with_attendance_permission_can_open_attendance_directly(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.ordinary_user_id
            sess["username"] = self.ordinary_user["username"]
        direct = self.client.get("/attendance_table")
        self.assertEqual(direct.status_code, 200)
        self.assertIn("Attendance Table", direct.data.decode())

    def test_08c_approved_user_without_attendance_cannot_open_attendance_directly(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.manager_user_id
            sess["username"] = self.manager_user["username"]
        direct = self.client.get("/attendance_table", follow_redirects=False)
        self.assertEqual(direct.status_code, 302)
        self.assertIn("/private-training/subscriptions", direct.location)

        follow = self.client.get("/attendance_table", follow_redirects=True)
        self.assertEqual(follow.status_code, 200)
        html = follow.data.decode()
        self.assertIn("Private Training Subscriptions", html)
        self.assertNotIn("Attendance Table", html)

    def test_09_super_admin_behaviour_remains_compatible(self):
        response = self._login(self.super_user["username"])
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            response.location.endswith("/attendance_table")
            or response.location.endswith("/home")
            or response.location.endswith("/")
        )

    def test_09b_trainer_logout_clears_session(self):
        self._login(self.trainer_user["username"])
        response = self.client.get("/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

        protected = self.client.get("/private-training/my-clients", follow_redirects=False)
        self.assertEqual(protected.status_code, 302)
        self.assertIn("/login", protected.location)

    def test_10_pending_approval_page_is_accessible_to_blocked_user(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.unapproved_user_id
            sess["username"] = self.unapproved_user["username"]
        response = self.client.get("/pending-approval")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("Your account is pending approval", html)
        self.assertIn("Logout", html)


if __name__ == "__main__":
    unittest.main()
