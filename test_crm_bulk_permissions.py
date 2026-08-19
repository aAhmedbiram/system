import unittest

from system_app.app import app
from system_app.queries import query_db


class TestCRMBulkPermissions(unittest.TestCase):
    def setUp(self):
        self._old_testing = app.config.get('TESTING')
        self._old_secret_key = app.config.get('SECRET_KEY')
        self._old_csrf_enabled = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['SECRET_KEY'] = 'test-secret'
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("Bulk Perm %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("bulkperm_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',             'rino@test.com',    'pwd', TRUE, '{}'),
            (49001, 'bulkperm_full',    'full@test.com',    'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_bulk_leads": true}'),
            (49002, 'bulkperm_create',   'create@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (49003, 'bulkperm_view',     'view@test.com',    'pwd', TRUE, '{"crm_view": true}'),
            (49004, 'bulkperm_assign',   'assign@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true, "crm_bulk_leads": true}'),
            (49005, 'bulkperm_bulk_only','bulk@test.com',    'pwd', TRUE, '{"crm_view": true, "crm_bulk_leads": true}'),
            (49006, 'bulkperm_none',     'none@test.com',    'pwd', TRUE, '{}'),
            (49007, 'bulkperm_super',    'super@test.com',   'pwd', TRUE, '{"super_admin": true}')
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("Bulk Perm %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("bulkperm_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member(self, member_id, name, end_date='2099-01-01'):
        query_db("""
            INSERT INTO members (
                id, name, phone, email, age, gender, birthdate, actual_starting_date,
                starting_date, end_date, membership_packages, membership_fees,
                membership_status, invitations, comment, national_id
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
        """, (
            member_id,
            name,
            f"09{member_id}",
            f"bulkperm{member_id}@example.com",
            None, None, None, None, None, end_date,
            'Gold', None, 'VAL', 0, None, None
        ), commit=True)

    def _page(self):
        return self.client.get('/crm/leads/bulk')

    def _members(self, params=None):
        return self.client.get('/crm/leads/bulk/members', query_string=params or {})

    def _preview(self, payload):
        return self.client.post('/crm/leads/bulk/preview', json=payload)

    def _execute(self, token):
        return self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})

    def test_01_dashboard_button_visible_with_bulk_permission(self):
        self.login_as('bulkperm_full', 49001)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Bulk Leads', res.data)
        self.assertIn(b'/crm/leads/bulk', res.data)

    def test_02_dashboard_button_hidden_without_bulk_permission(self):
        self.login_as('bulkperm_create', 49002)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertNotIn(b'Bulk Leads', res.data)
        self.assertNotIn(b'/crm/leads/bulk', res.data)

    def test_03_bulk_page_requires_bulk_permission(self):
        self.login_as('bulkperm_create', 49002)
        denied = self._page()
        self.assertIn(denied.status_code, [302, 403])

        self.login_as('bulkperm_full', 49001)
        allowed = self._page()
        self.assertEqual(allowed.status_code, 200)
        self.assertIn(b'Bulk CRM Leads', allowed.data)

    def test_04_bulk_page_allowed_for_bulk_only_user(self):
        self.login_as('bulkperm_bulk_only', 49005)
        res = self._page()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Bulk CRM Leads', res.data)

    def test_05_bulk_members_preview_execute_denied_without_bulk_permission(self):
        self.login_as('bulkperm_create', 49002)
        self.assertIn(self._members().status_code, [302, 403])
        self.assertIn(self._preview({
            "selection": {"mode": "ids", "member_ids": [1]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).status_code, [302, 403])
        self.assertIn(self._execute('token').status_code, [302, 403])

    def test_06_crm_create_alone_does_not_grant_bulk_or_equal(self):
        self.login_as('bulkperm_create', 49002)
        self._member(490101, 'Bulk Perm Member 1')
        self.assertIn(self.client.post('/crm/leads/bulk/preview', json={
            "selection": {"mode": "ids", "member_ids": [490101]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        }).status_code, [302, 403])

    def test_07_bulk_permission_does_not_grant_normal_create_or_assign(self):
        self.login_as('bulkperm_bulk_only', 49005)
        self.assertIn(self.client.post('/crm/leads', json={}).status_code, [302, 403])
        self.assertIn(self.client.get('/crm/users').status_code, [302, 403])
        self.assertIn(self.client.post('/crm/leads/1/assign', json={"user_id": 49001}).status_code, [302, 403])

    def test_08_equal_distribution_requires_crm_assign(self):
        self.login_as('bulkperm_full', 49001)
        self._member(490201, 'Bulk Perm Equal A')
        self._member(490202, 'Bulk Perm Equal B')
        denied = self._preview({
            "selection": {"mode": "ids", "member_ids": [490201, 490202]},
            "distribution": {"mode": "equal", "user_ids": [49004]},
            "source": "EXISTING_MEMBER"
        })
        self.assertIn(denied.status_code, [302, 403])

        self.login_as('bulkperm_assign', 49004)
        allowed = self._preview({
            "selection": {"mode": "ids", "member_ids": [490201, 490202]},
            "distribution": {"mode": "equal", "user_ids": [49004]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(allowed.status_code, 200)

    def test_09_bulk_assign_still_requires_crm_assign(self):
        self.login_as('bulkperm_bulk_only', 49005)
        denied = self.client.post('/crm/leads/bulk-assign', json={"lead_ids": [1], "user_id": 49004})
        self.assertIn(denied.status_code, [302, 403])

    def test_10_rino_and_super_admin_bypass_still_work(self):
        self.login_as('rino', 2)
        self.assertEqual(self._page().status_code, 200)

        self.login_as('bulkperm_super', 49007)
        self.assertEqual(self._page().status_code, 200)

    def test_11_user_permissions_ui_exposes_bulk_leads_label(self):
        self.login_as('rino', 2)
        res = self.client.get('/user_permissions')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'CRM - Bulk Leads', res.data)
        self.assertIn(b'crm_bulk_leads', res.data)


if __name__ == '__main__':
    unittest.main()
