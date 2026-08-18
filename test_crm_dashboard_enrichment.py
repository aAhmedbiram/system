from datetime import datetime, timedelta
from pathlib import Path
import unittest

from system_app.app import app
from system_app.crm.services import CAIRO_TZ
from system_app.queries import query_db


class TestCRMDashboardLeadTableEnrichment(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get("TESTING")
        self._old_secret_key = app.config.get("SECRET_KEY")
        self._old_csrf_enabled = app.config.get("WTF_CSRF_ENABLED")
        app.config["TESTING"] = True
        app.config["SECRET_KEY"] = "test-secret"
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("CRM Enrich %",), commit=True)
        query_db(
            "DELETE FROM users WHERE id IN (2, 49001)",
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',          'rino@test.com',  'pwd', TRUE, '{}'),
            (49001, 'crm_view_user',  'view@test.com',  'pwd', TRUE, '{"crm_view": true}')
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("CRM Enrich %",), commit=True)
        query_db(
            "DELETE FROM users WHERE id IN (2, 49001)",
            commit=True
        )
        app.config["TESTING"] = self._old_testing
        app.config["SECRET_KEY"] = self._old_secret_key
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username

    def _member(self, member_id, name, end_date="2099-12-31", phone=None):
        query_db(
            """
            INSERT INTO members (
                id, name, phone, email, age, gender, birthdate, actual_starting_date,
                starting_date, end_date, membership_packages, membership_fees,
                membership_status, invitations, comment, national_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                member_id,
                name,
                phone or f"01{member_id}",
                f"{name.lower().replace(' ', '')}@example.com",
                None,
                None,
                None,
                None,
                None,
                end_date,
                "Gold",
                None,
                "VAL",
                0,
                None,
                None,
            ),
            commit=True,
        )

    def _lead(self, lead_id, member_id=None, name="CRM Enrich Lead", phone="0100000000", created_by=2):
        query_db(
            """
            INSERT INTO crm_leads (
                id, member_id, name, phone, source, stage, created_by_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, 'WALK_IN', 'NEW', %s, FALSE)
            """,
            (lead_id, member_id, name, phone, created_by),
            commit=True,
        )

    def _activity(self, activity_id, lead_id, note, created_at, activity_type="NOTE"):
        query_db(
            """
            INSERT INTO crm_activities (
                id, lead_id, user_id, user_username_snapshot, activity_type, note, created_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (
                activity_id,
                lead_id,
                2,
                "rino",
                activity_type,
                note,
                created_at,
            ),
            commit=True,
        )

    def test_01_dashboard_headers_show_end_date_and_latest_activity(self):
        self.login_as("crm_view_user", 49001)
        res = self.client.get("/crm/")
        self.assertEqual(res.status_code, 200)
        self.assertIn(b"End Date", res.data)
        self.assertIn(b"Latest Activity", res.data)

    def test_02_member_end_date_and_prospect_dash_in_lead_list(self):
        self.login_as("rino", 2)
        self._member(8101, "CRM Enrich Member", "2099-12-31")
        self._lead(9101, member_id=8101, name="CRM Enrich Member", phone="0111118101")
        self._lead(9102, member_id=None, name="CRM Enrich Prospect", phone="0111118102")

        res = self.client.get("/crm/leads")
        self.assertEqual(res.status_code, 200)
        data = res.get_json()["items"]
        member_row = next(row for row in data if row["id"] == 9101)
        prospect_row = next(row for row in data if row["id"] == 9102)

        self.assertEqual(member_row["member_end_date"], "2099-12-31")
        self.assertIsNone(prospect_row.get("member_end_date"))

    def test_03_latest_activity_note_timestamp_and_tie_break(self):
        self.login_as("rino", 2)
        self._member(8201, "CRM Enrich Activity Member", "2099-12-31")
        self._lead(9201, member_id=8201, name="CRM Enrich Activity Lead", phone="0111118201")

        now = datetime.now(CAIRO_TZ)
        earlier = now - timedelta(hours=2)
        tie_time = now + timedelta(minutes=5)

        self._activity(9301, 9201, "Older activity note", earlier)
        self._activity(9302, 9201, "Tie lower id note", tie_time)
        self._activity(9303, 9201, "Latest note wins", tie_time)

        res = self.client.get("/crm/leads")
        self.assertEqual(res.status_code, 200)
        row = next(item for item in res.get_json()["items"] if item["id"] == 9201)

        self.assertEqual(row["latest_activity_note"], "Latest note wins")
        self.assertEqual(row["latest_activity_type"], "NOTE")
        self.assertTrue(row["latest_activity_at"])
        from email.utils import parsedate_to_datetime

        latest_at = parsedate_to_datetime(row["latest_activity_at"])
        self.assertEqual(latest_at.date(), tie_time.date())

    def test_04_blank_note_safe_and_no_activity_dash(self):
        self.login_as("rino", 2)
        self._member(8301, "CRM Enrich Blank Member", "2099-12-31")
        self._lead(9301, member_id=8301, name="CRM Enrich Blank Lead", phone="0111118301")
        self._lead(9302, member_id=None, name="CRM Enrich No Activity", phone="0111118302")

        blank_note_time = datetime.now(CAIRO_TZ)
        self._activity(9401, 9301, None, blank_note_time)

        res = self.client.get("/crm/leads")
        self.assertEqual(res.status_code, 200)
        rows = {row["id"]: row for row in res.get_json()["items"]}

        blank_note_row = rows[9301]
        no_activity_row = rows[9302]

        self.assertIsNone(blank_note_row["latest_activity_note"])
        self.assertTrue(blank_note_row["latest_activity_at"])
        self.assertIsNone(no_activity_row.get("latest_activity_note"))
        self.assertIsNone(no_activity_row.get("latest_activity_at"))

    def test_05_js_hooks_and_pagination_remain_intact(self):
        self.login_as("rino", 2)
        self._member(8401, "CRM Enrich Paging A", "2099-12-31")
        self._member(8402, "CRM Enrich Paging B", "2099-12-31")
        self._lead(9402, member_id=8401, name="CRM Enrich Paging Lead A", phone="0111118401")
        self._lead(9403, member_id=8402, name="CRM Enrich Paging Lead B", phone="0111118402")

        res = self.client.get("/crm/leads", query_string={"page": 1, "per_page": 1})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data["page"], 1)
        self.assertEqual(data["per_page"], 1)
        self.assertEqual(data["total"], 2)
        self.assertEqual(data["pages"], 2)

        js_path = Path(__file__).resolve().parent / "system_app" / "static" / "js" / "crm_leads.js"
        js_source = js_path.read_text(encoding="utf-8")
        self.assertIn("lead.member_end_date", js_source)
        self.assertIn("latest_activity_note", js_source)
        self.assertIn("truncateText(", js_source)
        self.assertIn("noteLine.title = latestNote", js_source)


if __name__ == "__main__":
    unittest.main()
