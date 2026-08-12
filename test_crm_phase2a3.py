import unittest
import datetime
from zoneinfo import ZoneInfo
from flask import session
from system_app.app import app
from system_app.queries import query_db

CAIRO_TZ = ZoneInfo("Africa/Cairo")

class TestCRMPhase2A3(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        # Setup standard users
        query_db("DELETE FROM users WHERE username IN ('rino', 'agent_a', 'agent_b', 'no_perm_user')", commit=True)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2, 'rino', 'rino@test.com', 'pwd', TRUE, '{}'),
            (20002, 'agent_a', 'agent_a@test.com', 'pwd', TRUE, '{"crm_view": true}'),
            (20003, 'agent_b', 'agent_b@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_all_leads": true}'),
            (20004, 'no_perm_user', 'no_perm@test.com', 'pwd', TRUE, '{}')
        """, commit=True)

        # Clean CRM leads and details
        query_db("DELETE FROM crm_leads", commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM users WHERE id IN (2, 20002, 20003, 20004)", commit=True)

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    # ==========================================
    # A. PIPELINE ENDPOINT VERIFICATION
    # ==========================================

    def test_pipeline_permissions(self):
        """Pipeline metrics route requires crm_view and login."""
        res = self.client.get('/crm/pipeline')
        self.assertEqual(res.status_code, 302)

        self.login_as('no_perm_user', 20004)
        res = self.client.get('/crm/pipeline')
        self.assertEqual(res.status_code, 302)

    def test_pipeline_counts_visibility(self):
        """Pipeline returns correct visibility counts based on user privileges."""
        # Insert leads for agent_a and agent_b
        query_db("""
            INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id)
            VALUES
            (101, 'Lead 1', '1', 'WALK_IN', 'NEW', 20002),
            (102, 'Lead 2', '2', 'FACEBOOK', 'CONTACTED', 20002),
            (103, 'Lead 3', '3', 'WALK_IN', 'NEW', 20003),
            (104, 'Lead 4', '4', 'WALK_IN', 'WON', 20003)
        """, commit=True)

        # Agent A (limited visibility) sees only their own
        self.login_as('agent_a', 20002)
        res = self.client.get('/crm/pipeline')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('NEW'), 1)
        self.assertEqual(data.get('CONTACTED'), 1)
        self.assertEqual(data.get('WON', 0), 0)

        # Rino sees everything
        self.login_as('rino', 2)
        res = self.client.get('/crm/pipeline')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data.get('NEW'), 2)
        self.assertEqual(data.get('WON'), 1)

    # ==========================================
    # B. FOLLOW-UP SUMMARY TESTS
    # ==========================================

    def test_follow_up_summary_security(self):
        """Follow-up summary requires login and crm_view."""
        res = self.client.get('/crm/follow-ups/summary')
        self.assertEqual(res.status_code, 302)

        self.login_as('no_perm_user', 20004)
        res = self.client.get('/crm/follow-ups/summary')
        self.assertEqual(res.status_code, 302)

    def test_follow_up_summary_bounds_and_filtering(self):
        """Follow-up summary counts overdue, today, upcoming correctly with mutually exclusive boundaries."""
        now_cairo = datetime.datetime.now(CAIRO_TZ)
        today_start = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = today_start + datetime.timedelta(days=1)

        # Disjoint buckets times
        yesterday_time = today_start - datetime.timedelta(hours=2) # Overdue (Yesterday)
        earlier_today_time = today_start + datetime.timedelta(minutes=30) # Today
        later_today_time = today_end - datetime.timedelta(minutes=30) # Today
        tomorrow_time = today_end + datetime.timedelta(hours=2) # Upcoming (Tomorrow)

        # Insert test leads for disjoint buckets
        query_db("""
            INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id, next_follow_up_at, is_archived)
            VALUES
            (201, 'Yesterday Lead', '1', 'WALK_IN', 'NEW', 20002, %s, FALSE),
            (202, 'Earlier Today Lead', '2', 'WALK_IN', 'CONTACTED', 20002, %s, FALSE),
            (203, 'Later Today Lead', '3', 'WALK_IN', 'FOLLOW_UP', 20002, %s, FALSE),
            (204, 'Tomorrow Lead', '4', 'WALK_IN', 'NEW', 20002, %s, FALSE),
            (205, 'Overdue Archived', '5', 'WALK_IN', 'NEW', 20002, %s, TRUE),
            (206, 'Overdue Won', '6', 'WALK_IN', 'WON', 20002, %s, FALSE),
            (207, 'Overdue Lost', '7', 'WALK_IN', 'LOST', 20002, %s, FALSE)
        """, (yesterday_time, earlier_today_time, later_today_time, tomorrow_time, yesterday_time, yesterday_time, yesterday_time), commit=True)

        self.login_as('agent_a', 20002)
        res = self.client.get('/crm/follow-ups/summary')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()

        # Check bounds filtering (excluding archived/WON/LOST leads)
        self.assertEqual(data['overdue'], 1)   # Lead 201 only
        self.assertEqual(data['today'], 2)     # Leads 202 and 203
        self.assertEqual(data['upcoming'], 1)  # Lead 204 only

        # Total active non-archived leads in summary should equal sum of counts
        total_eligible = query_db("""
            SELECT COUNT(*) as count FROM crm_leads
            WHERE is_archived = FALSE AND stage NOT IN ('WON', 'LOST') AND next_follow_up_at IS NOT NULL
        """, one=True)['count']
        self.assertEqual(data['overdue'] + data['today'] + data['upcoming'], total_eligible)

        # Cleanup disjoint leads
        query_db("DELETE FROM crm_leads", commit=True)

        # Test exact boundaries:
        # next_follow_up_at == today_start -> TODAY
        # next_follow_up_at == today_end -> UPCOMING
        query_db("""
            INSERT INTO crm_leads (id, name, phone, source, stage, assigned_user_id, next_follow_up_at, is_archived)
            VALUES
            (208, 'Exact Today Start', '8', 'WALK_IN', 'NEW', 20002, %s, FALSE),
            (209, 'Exact Today End', '9', 'WALK_IN', 'CONTACTED', 20002, %s, FALSE)
        """, (today_start, today_end), commit=True)

        res = self.client.get('/crm/follow-ups/summary')
        self.assertEqual(res.status_code, 200)
        boundary_data = res.get_json()

        self.assertEqual(boundary_data['overdue'], 0)
        self.assertEqual(boundary_data['today'], 1)    # 208 is exactly today_start
        self.assertEqual(boundary_data['upcoming'], 1) # 209 is exactly today_end

        # Cleanup boundary leads
        query_db("DELETE FROM crm_leads", commit=True)

    # ==========================================
    # C. LEADS API FILTER COMBINATIONS
    # ==========================================

    def test_leads_api_filters(self):
        """Leads API filters properly by search, stage, type, and source."""
        query_db("INSERT INTO members (id, name, phone) VALUES (50001, 'John Member', '222')", commit=True)
        query_db("""
            INSERT INTO crm_leads (id, name, phone, source, stage, member_id)
            VALUES
            (301, 'Ahmad Leads', '111', 'WALK_IN', 'NEW', NULL),
            (302, 'John Member', '222', 'FACEBOOK', 'WON', 50001),
            (303, 'Ahmad Other', '333', 'REFERRAL', 'CONTACTED', NULL)
        """, commit=True)

        self.login_as('rino', 2)

        # 1. Source filter
        res = self.client.get('/crm/leads?source=FACEBOOK')
        self.assertEqual(res.status_code, 200)
        items = res.get_json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], 302)

        # 2. Stage + Search filter combination
        res = self.client.get('/crm/leads?search=Ahmad&stage=NEW')
        self.assertEqual(res.status_code, 200)
        items = res.get_json()['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], 301)

        # Cleanup
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE id = 50001", commit=True)

if __name__ == '__main__':
    unittest.main()
