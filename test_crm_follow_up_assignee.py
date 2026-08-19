import unittest

from system_app.queries import query_db
from system_app.crm import queries


class TestCRMFollowUpAssignee(unittest.TestCase):
    def setUp(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db(
            "DELETE FROM users WHERE username = %s",
            ("followup_assignee_test",),
            commit=True
        )

        query_db("""
            INSERT INTO users (
                id, username, email, password, is_approved, permissions
            )
            VALUES (
                54001,
                %s,
                %s,
                'pwd',
                TRUE,
                '{"crm_view": true}'
            )
        """, (
            "followup_assignee_test",
            "followup_assignee_test@example.com"
        ), commit=True)

        query_db("""
            INSERT INTO crm_leads (
                id,
                name,
                phone,
                source,
                stage,
                assigned_user_id,
                next_follow_up_at,
                created_by_user_id,
                is_archived
            )
            VALUES (
                9201,
                'Follow Up Assigned Test',
                '01000000000',
                'WALK_IN',
                'CONTACTED',
                54001,
                CURRENT_TIMESTAMP + INTERVAL '7 days',
                54001,
                FALSE
            )
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db(
            "DELETE FROM users WHERE username = %s",
            ("followup_assignee_test",),
            commit=True
        )

    def test_follow_up_query_includes_assigned_username(self):
        rows = queries.get_follow_up_leads(
            ["l.id = %s"],
            [9201],
            20,
            0,
            "l.next_follow_up_at ASC"
        )

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["assigned_user_id"], 54001)
        self.assertEqual(
            rows[0]["assigned_username"],
            "followup_assignee_test"
        )


if __name__ == "__main__":
    unittest.main()
