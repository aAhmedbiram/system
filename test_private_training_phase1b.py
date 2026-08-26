import re
import unittest
from datetime import timedelta

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
    create_private_training_session_checkin,
    create_private_training_subscription,
    generate_portal_token,
    get_private_training_subscription,
    list_private_clients_for_trainer,
    reject_private_training_session,
    resolve_portal_token,
    revoke_portal_token,
    approve_private_training_session,
)


class PrivateTrainingPhase1BTest(unittest.TestCase):
    manager_user_id = 930001
    trainer_a_user_id = 930002
    trainer_b_user_id = 930003
    viewer_user_id = 930004
    no_perm_user_id = 930005
    pending_trainer_user_id = 930006
    super_admin_user_id = 930007
    mixed_user_id = 930008

    member_a_id = 940001
    member_b_id = 940002
    member_c_id = 940003
    member_d_id = 940004
    member_e_id = 940005
    member_f_id = 940006
    member_g_id = 940101
    member_h_id = 940102
    member_i_id = 940103

    def setUp(self):
        self._old_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        self._cleanup_private_training()
        self._cleanup_members()
        self._cleanup_users()
        self._upsert_users()
        self._upsert_members()

        self.manager_user = self._load_user(self.manager_user_id)
        self.trainer_a_user = self._load_user(self.trainer_a_user_id)
        self.trainer_b_user = self._load_user(self.trainer_b_user_id)
        self.viewer_user = self._load_user(self.viewer_user_id)
        self.no_perm_user = self._load_user(self.no_perm_user_id)
        self.pending_trainer_user = self._load_user(self.pending_trainer_user_id)
        self.super_admin_user = self._load_user(self.super_admin_user_id)
        self.mixed_user = self._load_user(self.mixed_user_id)

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
            (self.manager_user_id, "ptb_manager", "ptb_manager@test.local", True, {"private_training_manage": True}),
            (self.trainer_a_user_id, "ptb_trainer_a", "ptb_trainer_a@test.local", True, {"private_training_trainer": True}),
            (self.trainer_b_user_id, "ptb_trainer_b", "ptb_trainer_b@test.local", True, {"private_training_trainer": True}),
            (self.viewer_user_id, "ptb_viewer", "ptb_viewer@test.local", True, {"private_training_view": True}),
            (self.no_perm_user_id, "ptb_no_perm", "ptb_no_perm@test.local", True, {}),
            (self.pending_trainer_user_id, "ptb_pending_trainer", "ptb_pending_trainer@test.local", False, {"private_training_trainer": True}),
            (self.super_admin_user_id, "ptb_super_admin", "ptb_super_admin@test.local", True, {"super_admin": True}),
            (self.mixed_user_id, "ptb_mixed", "ptb_mixed@test.local", True, {"private_training_trainer": True, "private_training_manage": True}),
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
        members = [
            (self.member_a_id, "PTB Member A", "880001"),
            (self.member_b_id, "PTB Member B", "880002"),
            (self.member_c_id, "PTB Member C", "880003"),
            (self.member_d_id, "PTB Member D", "880004"),
            (self.member_e_id, "PTB Member E", "880005"),
            (self.member_f_id, "PTB Member F", "880006"),
            (self.member_g_id, "PTB Search Alpha", "880101"),
            (self.member_h_id, "PTB Expired Search", "880102"),
            (self.member_i_id, "PTB Phone Clash", "94000199"),
        ]
        for member_id, name, phone in members:
            if member_id == self.member_h_id:
                membership_status = "EX"
                start_date = self._date_str(-60)
                end_date = self._date_str(-1)
            else:
                membership_status = "VAL"
                start_date = self._date_str(-1)
                end_date = self._date_str(30)
            query_db(
                """
                INSERT INTO members (
                    id, name, phone, membership_packages, membership_fees,
                    membership_status, starting_date, end_date
                ) VALUES (%s, %s, %s, '1 Month', 500.0, %s, %s, %s)
                ON CONFLICT (id) DO UPDATE SET
                    name = EXCLUDED.name,
                    phone = EXCLUDED.phone,
                    membership_packages = EXCLUDED.membership_packages,
                    membership_fees = EXCLUDED.membership_fees,
                    membership_status = EXCLUDED.membership_status,
                    starting_date = EXCLUDED.starting_date,
                    end_date = EXCLUDED.end_date
                """,
                (member_id, name, phone, membership_status, start_date, end_date),
                commit=True,
            )

    def _cleanup_private_training(self):
        query_db(
            """
            DELETE FROM private_training_portal_tokens
            WHERE subscription_id IN (
                SELECT id FROM private_training_subscriptions
               WHERE member_id IN (940001, 940002, 940003, 940004, 940005, 940006, 940101, 940102, 940103)
                   OR trainer_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
                   OR created_by_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_sessions
            WHERE subscription_id IN (
                SELECT id FROM private_training_subscriptions
               WHERE member_id IN (940001, 940002, 940003, 940004, 940005, 940006, 940101, 940102, 940103)
                   OR trainer_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
                   OR created_by_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
            )
            """,
            commit=True,
        )
        query_db(
            """
            DELETE FROM private_training_subscriptions
            WHERE member_id IN (940001, 940002, 940003, 940004, 940005, 940006, 940101, 940102, 940103)
               OR trainer_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
               OR created_by_user_id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)
            """,
            commit=True,
        )

    def _cleanup_members(self):
        query_db("DELETE FROM members WHERE id IN (940001, 940002, 940003, 940004, 940005, 940006, 940101, 940102, 940103)", commit=True)

    def _cleanup_users(self):
        query_db("DELETE FROM users WHERE id IN (930001, 930002, 930003, 930004, 930005, 930006, 930007, 930008)", commit=True)

    def _load_user(self, user_id):
        return query_db(
            "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
            (user_id,),
            one=True,
        )

    def _create_subscription(self, member_id, trainer_user_id, total_sessions=2, start_offset_days=0, expiry_offset_days=30):
        result = create_private_training_subscription(
            self.manager_user,
            member_id,
            trainer_user_id,
            total_sessions,
            self._date_str(start_offset_days),
            self._date_str(expiry_offset_days),
        )
        return result["subscription"]

    def _make_active_subscription(self, member_id, trainer_user_id=None, total_sessions=2):
        trainer_user_id = trainer_user_id or self.trainer_a_user_id
        return self._create_subscription(member_id, trainer_user_id, total_sessions=total_sessions, start_offset_days=0, expiry_offset_days=30)

    def _make_future_subscription(self, member_id, trainer_user_id=None, total_sessions=2):
        trainer_user_id = trainer_user_id or self.trainer_a_user_id
        return self._create_subscription(member_id, trainer_user_id, total_sessions=total_sessions, start_offset_days=2, expiry_offset_days=30)

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

    def _approve_latest_pending(self, subscription_id):
        pending = query_db(
            """
            SELECT *
            FROM private_training_sessions
            WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL'
            ORDER BY id DESC
            LIMIT 1
            """,
            (subscription_id,),
            one=True,
        )
        return approve_private_training_session(subscription_id, pending["id"], {"subscription_id": subscription_id})

    def _reject_latest_pending(self, subscription_id, reason):
        pending = query_db(
            """
            SELECT *
            FROM private_training_sessions
            WHERE subscription_id = %s AND status = 'PENDING_MEMBER_APPROVAL'
            ORDER BY id DESC
            LIMIT 1
            """,
            (subscription_id,),
            one=True,
        )
        return reject_private_training_session(subscription_id, pending["id"], reason, {"subscription_id": subscription_id})

    def _extract_generated_url(self, html):
        match = re.search(r'value="(https?://[^"]+/private-training/member/([A-Za-z0-9_-]+))"', html)
        self.assertIsNotNone(match, "Expected generated portal URL to be rendered")
        return match.group(1), match.group(2)

    def test_01_manage_user_can_open_create_page(self):
        self._login_as(self.manager_user)
        response = self.client.get("/private-training/subscriptions/new")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"New Private Subscription", response.data)

    def test_02_unauthorized_user_denied_create_page(self):
        self._login_as(self.no_perm_user)
        response = self.client.get("/private-training/subscriptions/new")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/attendance_table", response.location)

    def test_03_create_form_includes_required_fields(self):
        self._login_as(self.manager_user)
        response = self.client.get("/private-training/subscriptions/new")
        html = response.data.decode()
        self.assertIn('name="member_id"', html)
        self.assertIn('name="trainer_user_id"', html)
        self.assertIn('name="total_sessions"', html)
        self.assertIn('name="private_start_date"', html)
        self.assertIn('name="private_expiry_date"', html)

    def test_03b_default_member_results_only_include_active_members(self):
        self._login_as(self.manager_user)
        response = self.client.get("/private-training/subscriptions/new")
        html = response.data.decode()
        self.assertIn("PTB Member A", html)
        self.assertIn("PTB Search Alpha", html)
        self.assertIn("PTB Phone Clash", html)
        self.assertNotIn("PTB Expired Search", html)

    def test_03c_numeric_member_id_search_prioritizes_exact_id(self):
        self._login_as(self.manager_user)
        response = self.client.get(
            "/private-training/subscriptions/new",
            query_string={"q": str(self.member_a_id)},
        )
        html = response.data.decode()
        exact_index = html.index(f'value="{self.member_a_id}"')
        phone_match_index = html.index(f'value="{self.member_i_id}"')
        self.assertLess(exact_index, phone_match_index)

    def test_03d_name_partial_search_works(self):
        self._login_as(self.manager_user)
        response = self.client.get(
            "/private-training/subscriptions/new",
            query_string={"q": "Search Alpha"},
        )
        html = response.data.decode()
        self.assertIn("PTB Search Alpha", html)
        self.assertNotIn("PTB Expired Search", html)

    def test_03e_phone_search_works(self):
        self._login_as(self.manager_user)
        response = self.client.get(
            "/private-training/subscriptions/new",
            query_string={"q": "880002"},
        )
        html = response.data.decode()
        self.assertIn("PTB Member B", html)
        self.assertNotIn("PTB Member C", html)

    def test_04_trainer_selector_only_includes_approved_private_training_trainers(self):
        self._login_as(self.manager_user)
        response = self.client.get("/private-training/subscriptions/new")
        html = response.data.decode()
        self.assertIn("ptb_trainer_a", html)
        self.assertIn("ptb_trainer_b", html)
        self.assertIn("ptb_mixed", html)
        self.assertNotIn("ptb_no_perm", html)
        self.assertNotIn("ptb_pending_trainer", html)
        self.assertNotIn("ptb_super_admin", html)

    def test_04b_empty_trainer_state_renders_useful_message(self):
        self._login_as(self.manager_user)
        for user_id in (self.trainer_a_user_id, self.trainer_b_user_id, self.mixed_user_id):
            permissions = dict(self._load_user(user_id).get("permissions") or {})
            permissions["private_training_trainer"] = False
            query_db(
                "UPDATE users SET permissions = %s WHERE id = %s",
                (Json(permissions), user_id),
                commit=True,
            )
        response = self.client.get("/private-training/subscriptions/new")
        html = response.data.decode()
        self.assertIn("No Private Training trainers are configured.", html)

    def test_05_invalid_member_rejected(self):
        self._login_as(self.manager_user)
        response = self.client.post(
            "/private-training/subscriptions",
            data={
                "member_id": 999999,
                "trainer_user_id": self.trainer_a_user_id,
                "total_sessions": 2,
                "private_start_date": self._date_str(1),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_06_invalid_trainer_rejected(self):
        self._login_as(self.manager_user)
        response = self.client.post(
            "/private-training/subscriptions",
            data={
                "member_id": self.member_a_id,
                "trainer_user_id": 999998,
                "total_sessions": 2,
                "private_start_date": self._date_str(1),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(response.status_code, 400)

    def test_06b_super_admin_without_trainer_permission_rejected(self):
        self._login_as(self.manager_user)
        response = self.client.post(
            "/private-training/subscriptions",
            data={
                "member_id": self.member_a_id,
                "trainer_user_id": self.super_admin_user_id,
                "total_sessions": 2,
                "private_start_date": self._date_str(1),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("Trainer user does not have private_training_trainer permission", response.data.decode())

    def test_07_successful_create_persists_correct_data(self):
        self._login_as(self.manager_user)
        response = self.client.post(
            "/private-training/subscriptions",
            data={
                "member_id": self.member_a_id,
                "trainer_user_id": self.trainer_a_user_id,
                "total_sessions": 3,
                "private_start_date": self._date_str(1),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(response.status_code, 302)
        subscription = query_db(
            "SELECT * FROM private_training_subscriptions WHERE member_id = %s ORDER BY id DESC LIMIT 1",
            (self.member_a_id,),
            one=True,
        )
        self.assertIsNotNone(subscription)
        self.assertEqual(subscription["trainer_user_id"], self.trainer_a_user_id)
        self.assertEqual(subscription["created_by_user_id"], self.manager_user_id)
        self.assertEqual(subscription["total_sessions"], 3)
        self.assertEqual(subscription["private_start_date"].isoformat(), self._date_str(1))
        self.assertEqual(subscription["private_expiry_date"].isoformat(), self._date_str(30))

    def test_08_duplicate_effective_active_subscription_rejected(self):
        self._login_as(self.manager_user)
        self._create_subscription(self.member_b_id, self.trainer_a_user_id, total_sessions=2, start_offset_days=0, expiry_offset_days=30)
        response = self.client.post(
            "/private-training/subscriptions",
            data={
                "member_id": self.member_b_id,
                "trainer_user_id": self.trainer_b_user_id,
                "total_sessions": 2,
                "private_start_date": self._date_str(1),
                "private_expiry_date": self._date_str(30),
            },
        )
        self.assertEqual(response.status_code, 409)

    def test_09_manager_can_access_subscription_list(self):
        self._login_as(self.manager_user)
        response = self.client.get("/private-training/subscriptions")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Private Training Subscriptions", response.data)

    def test_10_trainer_can_open_my_clients(self):
        self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get("/private-training/my-clients")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"My Private Clients", response.data)
        self.assertNotIn(b"All Visible Subscriptions", response.data)

    def test_10b_mixed_permission_user_sees_cross_trainer_link(self):
        self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.mixed_user)
        response = self.client.get("/private-training/my-clients")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"All Visible Subscriptions", response.data)

    def test_11_trainer_sees_own_assigned_client(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get("/private-training/my-clients")
        html = response.data.decode()
        self.assertIn("PTB Member A", html)
        self.assertIn(str(subscription["id"]), html)

    def test_12_trainer_does_not_see_other_trainers_client(self):
        self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._create_subscription(self.member_b_id, self.trainer_b_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get("/private-training/my-clients")
        html = response.data.decode()
        self.assertIn("PTB Member A", html)
        self.assertNotIn("PTB Member B", html)

    def test_13_another_trainer_cannot_open_detail_url(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_b_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        self.assertEqual(response.status_code, 302)

    def test_14_detail_page_displays_counts_and_gym_details(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Gym Details", html)
        self.assertIn("PTB Member A", html)
        self.assertIn("1 Month", html)
        self.assertIn("Approved Sessions: 0", html)
        self.assertIn("Remaining Sessions: 2", html)
        self.assertIn("Pending Sessions: 0", html)

    def test_14b_manager_sees_read_only_status_but_no_portal_controls(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.manager_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Status: <strong>No active token</strong>", html)
        self.assertNotIn("Generate Link", html)
        self.assertNotIn("Revoke Link", html)

    def test_14c_assigned_trainer_sees_portal_controls(self):
        subscription = self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Generate Link", html)
        self.assertIn("Revoke Link", html)

    def test_14d_super_admin_without_trainer_permission_is_not_assignable_but_can_manage_token(self):
        self._login_as(self.manager_user)
        create_response = self.client.get("/private-training/subscriptions/new")
        self.assertNotIn("ptb_super_admin", create_response.data.decode())

        subscription = self._create_subscription(self.member_b_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.super_admin_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Generate Link", html)
        self.assertIn("Revoke Link", html)

    def test_15_effective_status_displayed(self):
        subscription = self._make_active_subscription(self.member_c_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        self.assertIn(b"Effective Status", response.data)
        self.assertIn(b"ACTIVE", response.data)

    def test_16_approved_remaining_pending_counts_displayed(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=2)
        first_session = create_private_training_session_checkin(self.trainer_a_user, subscription["id"])
        approve_private_training_session(subscription["id"], first_session["id"], {"subscription_id": subscription["id"]})
        create_private_training_session_checkin(self.trainer_a_user, subscription["id"])
        self._login_as(self.trainer_a_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        html = response.data.decode()
        self.assertIn("Approved Sessions: 1", html)
        self.assertIn("Remaining Sessions: 1", html)
        self.assertIn("Pending Sessions: 1", html)

    def test_17_correct_trainer_can_generate_portal_link(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("Active link exists", html)
        generated_url, raw_token = self._extract_generated_url(html)
        self.assertIn("/private-training/member/", generated_url)
        self.assertIn(raw_token, generated_url)
        token_row = query_db(
            "SELECT * FROM private_training_portal_tokens WHERE subscription_id = %s AND revoked_at IS NULL ORDER BY id DESC LIMIT 1",
            (subscription["id"],),
            one=True,
        )
        self.assertIsNotNone(token_row)
        self.assertNotIn(token_row["token_hash"], html)
        self.assertEqual(resolve_portal_token(raw_token)["subscription"]["id"], subscription["id"])

    def test_18_raw_token_displayed_once_and_hidden_after_reload(self):
        subscription = self._make_active_subscription(self.member_b_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        html = response.data.decode()
        generated_url, raw_token = self._extract_generated_url(html)
        self.assertEqual(html.count(raw_token), 1)

        reload_response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        reload_html = reload_response.data.decode()
        self.assertNotIn(raw_token, reload_html)
        self.assertIn("Active link exists", reload_html)
        self.assertIn("No raw portal token is shown on this page load", reload_html)
        self.assertIn(generated_url.rsplit("/", 1)[0], html)

    def test_19_correct_trainer_can_revoke_token(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        revoke_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token/revoke", follow_redirects=True)
        self.assertEqual(revoke_response.status_code, 200)
        self.assertIn(b"No active token", revoke_response.data)

    def test_20_revoked_token_no_longer_resolves(self):
        subscription = self._make_active_subscription(self.member_c_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        generate_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        raw_token = self._extract_generated_url(generate_response.data.decode())[1]
        self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token/revoke")
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(raw_token)

    def test_21_regenerate_invalidates_old_token(self):
        subscription = self._make_active_subscription(self.member_d_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        first_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        first_token = self._extract_generated_url(first_response.data.decode())[1]
        second_response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        second_token = self._extract_generated_url(second_response.data.decode())[1]
        with self.assertRaises(PrivateTrainingNotFoundError):
            resolve_portal_token(first_token)
        self.assertEqual(resolve_portal_token(second_token)["subscription"]["id"], subscription["id"])

    def test_22_wrong_trainer_cannot_generate_token(self):
        subscription = self._make_active_subscription(self.member_a_id, trainer_user_id=self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_b_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("Active link exists", response.data.decode())
        self.assertIsNone(query_db("SELECT * FROM private_training_portal_tokens WHERE subscription_id = %s AND revoked_at IS NULL", (subscription["id"],), one=True))

    def test_23_wrong_trainer_cannot_revoke_token(self):
        subscription = self._make_active_subscription(self.member_b_id, trainer_user_id=self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.trainer_a_user)
        self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token")
        self._login_as(self.trainer_b_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token/revoke", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("You cannot access that private training subscription.", response.data.decode())
        self.assertIsNotNone(query_db("SELECT * FROM private_training_portal_tokens WHERE subscription_id = %s AND revoked_at IS NULL", (subscription["id"],), one=True))

    def test_24_completed_subscription_cannot_generate_active_link(self):
        subscription = self._create_subscription(self.member_e_id, self.trainer_a_user_id, total_sessions=1)
        session_row = create_private_training_session_checkin(self.trainer_a_user, subscription["id"])
        approve_private_training_session(subscription["id"], session_row["id"], {"subscription_id": subscription["id"]})
        self._login_as(self.trainer_a_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Subscription is completed", response.data.decode())

    def test_25_expired_subscription_cannot_generate_active_link(self):
        subscription = self._make_active_subscription(self.member_f_id, total_sessions=2)
        self._expire_subscription(subscription["id"])
        self._login_as(self.trainer_a_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Subscription is expired", response.data.decode())

    def test_26_cancelled_subscription_cannot_generate_active_link(self):
        subscription = self._make_active_subscription(self.member_a_id, total_sessions=2)
        query_db(
            "UPDATE private_training_subscriptions SET status = 'CANCELLED' WHERE id = %s",
            (subscription["id"],),
            commit=True,
        )
        self._login_as(self.trainer_a_user)
        response = self.client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Subscription is cancelled", response.data.decode())

    def test_27_create_post_requires_csrf(self):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            csrf_client = app.test_client()
            with csrf_client.session_transaction() as sess:
                sess["user_id"] = self.manager_user_id
                sess["username"] = self.manager_user["username"]
            response = csrf_client.post(
                "/private-training/subscriptions",
                data={
                    "member_id": self.member_a_id,
                    "trainer_user_id": self.trainer_a_user_id,
                    "total_sessions": 2,
                    "private_start_date": self._date_str(1),
                    "private_expiry_date": self._date_str(30),
                },
            )
            self.assertEqual(response.status_code, 400)
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_28_token_post_requires_csrf(self):
        app.config["WTF_CSRF_ENABLED"] = True
        try:
            csrf_client = app.test_client()
            subscription = self._make_active_subscription(self.member_b_id, total_sessions=2)
            with csrf_client.session_transaction() as sess:
                sess["user_id"] = self.trainer_a_user_id
                sess["username"] = self.trainer_a_user["username"]
            response = csrf_client.post(f"/private-training/subscriptions/{subscription['id']}/portal-token", data={})
            self.assertEqual(response.status_code, 400)
        finally:
            app.config["WTF_CSRF_ENABLED"] = False

    def test_29_anonymous_user_blocked_from_staff_routes(self):
        response = self.client.get("/private-training/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.location)

    def test_30_existing_member_page_remains_functional(self):
        self._login_as(self.manager_user)
        response = self.client.post("/show_member_data", data={"member_id": self.member_a_id})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertIn("PTB Member A", html)
        self.assertIn("Add Private Training", html)

    def test_30b_trainer_only_does_not_see_private_training_member_action(self):
        self._login_as(self.trainer_a_user)
        response = self.client.post("/show_member_data", data={"member_id": self.member_a_id})
        self.assertEqual(response.status_code, 200)
        html = response.data.decode()
        self.assertNotIn("Add Private Training", html)

    def test_31_existing_attendance_route_smoke(self):
        self._login_as(self.manager_user)
        response = self.client.get("/attendance_table")
        self.assertIn(response.status_code, (200, 302))

    def test_32_permission_list_and_service_scoping_remain_consistent(self):
        self._create_subscription(self.member_a_id, self.trainer_a_user_id, total_sessions=2)
        self._create_subscription(self.member_b_id, self.trainer_b_user_id, total_sessions=2)
        trainer_rows = list_private_clients_for_trainer(self.trainer_a_user)
        trainer_ids = {row["trainer_user_id"] for row in trainer_rows}
        self.assertIn(self.trainer_a_user_id, trainer_ids)
        self.assertNotIn(self.trainer_b_user_id, trainer_ids)

    def test_33_detail_view_allows_manager_access(self):
        subscription = self._create_subscription(self.member_c_id, self.trainer_a_user_id, total_sessions=2)
        self._login_as(self.manager_user)
        response = self.client.get(f"/private-training/subscriptions/{subscription['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn("PTB Member C", response.data.decode())

    def test_34_focused_phase1a_services_still_work(self):
        subscription = self._make_future_subscription(self.member_d_id, total_sessions=2)
        self.assertEqual(get_private_training_subscription(subscription["id"])["id"], subscription["id"])

    def test_35_session_checkin_and_approval_flow_still_works(self):
        subscription = self._make_active_subscription(self.member_e_id, total_sessions=2)
        session_row = create_private_training_session_checkin(self.trainer_a_user, subscription["id"])
        approve_private_training_session(subscription["id"], session_row["id"], {"subscription_id": subscription["id"]})
        counts = query_db(
            """
            SELECT
                COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved_count,
                COUNT(*) FILTER (WHERE status = 'PENDING_MEMBER_APPROVAL') AS pending_count
            FROM private_training_sessions
            WHERE subscription_id = %s
            """,
            (subscription["id"],),
            one=True,
        )
        self.assertEqual(int(counts["approved_count"]), 1)
        self.assertEqual(int(counts["pending_count"]), 0)


if __name__ == "__main__":
    unittest.main()
