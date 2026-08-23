from datetime import datetime
from pathlib import Path
import unittest

from system_app.app import app
from system_app.queries import query_db


class TestCRMBulkInvitationsPhase4(unittest.TestCase):
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
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM invitations WHERE id BETWEEN %s AND %s", (89500, 89599), commit=True)
        query_db("DELETE FROM members WHERE id BETWEEN %s AND %s", (79500, 79599), commit=True)
        query_db("DELETE FROM users WHERE id BETWEEN %s AND %s", (59500, 59599), commit=True)

        query_db(
            """
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (59501, 'p4_bulk', 'bulk@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_bulk_leads": true}'),
            (59502, 'p4_none', 'none@test.com', 'pwd', TRUE, '{}')
            """
            ,
            commit=True
        )
        self._member(79501, "P4 Inviter", "01099999501")
        self._invitation(89501, "Phase Four Friend", "01044440001", datetime(2026, 8, 20, 10, 0, 0))

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM invitations WHERE id BETWEEN %s AND %s", (89500, 89599), commit=True)
        query_db("DELETE FROM members WHERE id BETWEEN %s AND %s", (79500, 79599), commit=True)
        query_db("DELETE FROM users WHERE id BETWEEN %s AND %s", (59500, 59599), commit=True)
        app.config["TESTING"] = self._old_testing
        app.config["SECRET_KEY"] = self._old_secret_key
        app.config["WTF_CSRF_ENABLED"] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess["user_id"] = user_id
            sess["username"] = username

    def _member(self, member_id, name, phone):
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
                phone,
                f"{name.lower().replace(' ', '')}@example.com",
                None, None, None, None, None, "2099-01-01",
                "Gold", None, "VAL", 0, None, None
            ),
            commit=True
        )

    def _invitation(self, invitation_id, friend_name, friend_phone, used_date, used_by="p4_user"):
        query_db(
            """
            INSERT INTO invitations (
                id, member_id, member_name, friend_name, friend_phone, friend_email,
                used_date, used_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                invitation_id,
                79501,
                "P4 Inviter",
                friend_name,
                friend_phone,
                f"{friend_name.lower().replace(' ', '')}@example.com",
                used_date,
                used_by,
            ),
            commit=True
        )

    def _preview_page(self, token=None):
        if token:
            return self.client.get("/crm/leads/bulk", query_string={"preview_token": token})
        return self.client.get("/crm/leads/bulk")

    def test_01_bulk_page_exposes_source_selector_and_invitation_controls(self):
        self.login_as("p4_bulk", 59501)
        response = self._preview_page()
        self.assertEqual(response.status_code, 200)
        html = response.data.decode("utf-8")

        self.assertIn('id="bulkSourceMembersBtn"', html)
        self.assertIn('id="bulkSourceInvitationsBtn"', html)
        self.assertIn('id="memberFiltersPanel"', html)
        self.assertIn('id="invitationFiltersPanel"', html)
        self.assertIn('id="bulkInvitationSearchName"', html)
        self.assertIn('id="bulkInvitationSearchPhone"', html)
        self.assertIn('id="bulkInvitationUsedBy"', html)
        self.assertIn('id="bulkInvitationMonth"', html)
        self.assertIn('id="bulkInvitationYear"', html)
        self.assertIn('id="bulkMembersTableHead"', html)
        self.assertIn('id="selectionSectionTitle"', html)
        self.assertIn('id="selectionSectionNote"', html)
        self.assertIn('id="bulkSourceMembersBtn" class="btn btn-secondary active"', html)
        self.assertIn('id="bulkSourceInvitationsBtn" class="btn btn-secondary"', html)
        self.assertNotIn("previewTokenInput", html)

    def test_02_invitation_listing_requires_bulk_permission_and_returns_candidate_fields(self):
        self.login_as("p4_none", 59502)
        denied = self.client.get("/crm/leads/bulk/invitations")
        self.assertIn(denied.status_code, [302, 403])

        self.login_as("p4_bulk", 59501)
        response = self.client.get("/crm/leads/bulk/invitations", query_string={"per_page": 50})
        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("items", data)
        self.assertIn("total", data)
        self.assertIn("pages", data)
        self.assertGreaterEqual(data["total"], 1)
        item = next(row for row in data["items"] if row["candidate_key"] == "01044440001")
        self.assertEqual(item["invitation_id"], 89501)
        self.assertEqual(item["name"], "Phase Four Friend")
        self.assertEqual(item["phone"], "01044440001")
        self.assertEqual(item["email"], "phasefourfriend@example.com")
        self.assertEqual(item["used_by"], "p4_user")
        self.assertEqual(item["inviter_member_id"], 79501)
        self.assertEqual(item["inviter_name"], "P4 Inviter")
        self.assertIn("used_date", item)

    def test_03_preview_restore_shows_invitation_source(self):
        self.login_as("p4_bulk", 59501)
        preview = self.client.post(
            "/crm/leads/bulk/preview",
            json={
                "source": "INVITATIONS",
                "selection": {"mode": "ids", "candidate_keys": ["01044440001"]},
                "distribution": {"mode": "unassigned"}
            }
        )
        self.assertEqual(preview.status_code, 200)
        token = preview.get_json()["preview_token"]

        page = self._preview_page(token)
        self.assertEqual(page.status_code, 200)
        html = page.data.decode("utf-8")
        self.assertIn("INVITATIONS", html)
        self.assertIn("previewTokenDebug", html)
        self.assertIn("bulkSourceInvitationsBtn", html)

    def test_04_js_contract_includes_source_switch_and_invitation_filters(self):
        js = Path("system_app/static/js/crm_bulk_leads.js").read_text(encoding="utf-8")
        self.assertIn("state.source", js)
        self.assertIn("sourceState", js)
        self.assertIn("bulkSourceMembersBtn", js)
        self.assertIn("bulkSourceInvitationsBtn", js)
        self.assertIn("sourceQueryPath()", js)
        self.assertIn("candidate_keys", js)
        self.assertIn("bulkInvitationSearchName", js)
        self.assertIn("bulkInvitationUsedBy", js)
        self.assertIn("bulkInvitationMonth", js)
        self.assertIn("bulkInvitationYear", js)
        self.assertIn("bulkMembersTableHead", js)
        self.assertIn("setActiveSource(", js)
        self.assertIn("nextUrl.searchParams.set(\"source\", SOURCE_INVITATIONS)", js)


if __name__ == "__main__":
    unittest.main()
