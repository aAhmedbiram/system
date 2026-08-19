import unittest
from pathlib import Path

from system_app.app import app
from system_app.queries import query_db


class TestCRMAssignedFilter(unittest.TestCase):
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
        query_db("DELETE FROM members WHERE name LIKE %s", ("Assigned Filter %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("assignedfilter_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',                     'rino@test.com',     'pwd', TRUE, '{}'),
            (53001, 'assignedfilter_restricted','restricted@test.com','pwd', TRUE, '{"crm_view": true}'),
            (53002, 'assignedfilter_all',       'all@test.com',      'pwd', TRUE, '{"crm_view": true, "crm_all_leads": true}'),
            (53003, 'assignedfilter_assign',    'assign@test.com',   'pwd', TRUE, '{"crm_view": true, "crm_assign": true}'),
            (53004, 'assignedfilter_view',      'view@test.com',     'pwd', TRUE, '{"crm_view": true}'),
            (53005, 'assignedfilter_super',     'super@test.com',    'pwd', TRUE, '{"super_admin": true}'),
            (53006, 'assignedfilter_emp_a',     'a@test.com',        'pwd', TRUE, '{"crm_view": true}'),
            (53007, 'assignedfilter_emp_b',     'b@test.com',        'pwd', TRUE, '{"crm_view": true}')
        """, commit=True)

        self._insert_lead(9101, 'Assigned Filter A', '111001', 'WALK_IN', 'NEW', 53001, 53006)
        self._insert_lead(9102, 'Assigned Filter B', '111002', 'EXISTING_MEMBER', 'CONTACTED', 53001, 53006)
        self._insert_lead(9103, 'Assigned Filter C', '111003', 'EXISTING_MEMBER', 'NEW', 53001, 53007)
        self._insert_lead(9104, 'Assigned Filter D', '111004', 'WALK_IN', 'NEW', 53001, None)
        self._insert_lead(9105, 'Alpha Search Match', '111005', 'EXISTING_MEMBER', 'NEW', 53001, 53006)
        self._insert_lead(9106, 'Beta Search Match', '111006', 'EXISTING_MEMBER', 'NEW', 53001, 53007)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("Assigned Filter %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("assignedfilter_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _insert_lead(self, lead_id, name, phone, source, stage, created_by_user_id, assigned_user_id):
        query_db("""
            INSERT INTO crm_leads (
                id, name, phone, source, stage, created_by_user_id,
                assigned_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, FALSE)
        """, (
            lead_id, name, phone, source, stage, created_by_user_id, assigned_user_id
        ), commit=True)

    def _get_leads(self, params=None):
        return self.client.get('/crm/leads', query_string=params or {})

    def test_01_all_employees_preserves_authorized_result_set(self):
        self.login_as('assignedfilter_all', 53002)
        base = self._get_leads()
        explicit_blank = self._get_leads({'assigned_user_id': ''})
        self.assertEqual(base.status_code, 200)
        self.assertEqual(explicit_blank.status_code, 200)
        self.assertEqual(base.get_json()['total'], explicit_blank.get_json()['total'])
        self.assertEqual(
            [row['id'] for row in base.get_json()['items']],
            [row['id'] for row in explicit_blank.get_json()['items']]
        )

    def test_02_specific_employee_filters_assigned_leads(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53006})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(
            sorted(row['id'] for row in data['items']),
            [9101, 9102, 9105]
        )
        self.assertEqual(data['total'], 3)

    def test_03_unassigned_filters_null_assignments(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 'unassigned'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual([row['id'] for row in data['items']], [9104])
        self.assertEqual(data['total'], 1)
        self.assertIsNone(data['items'][0]['assigned_user_id'])

    def test_04_assigned_to_combines_with_stage(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53006, 'stage': 'NEW'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(
            sorted(row['id'] for row in data['items']),
            [9101, 9105]
        )
        self.assertEqual(data['total'], 2)

    def test_05_assigned_to_combines_with_source(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53006, 'source': 'EXISTING_MEMBER'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(
            sorted(row['id'] for row in data['items']),
            [9102, 9105]
        )
        self.assertEqual(data['total'], 2)

    def test_06_assigned_to_combines_with_search(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53006, 'search': 'Alpha'})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual([row['id'] for row in data['items']], [9105])
        self.assertEqual(data['total'], 1)

    def test_07_pagination_counts_remain_correct(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53006, 'page': 1, 'per_page': 2})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 3)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(len(data['items']), 2)

        res_page2 = self._get_leads({'assigned_user_id': 53006, 'page': 2, 'per_page': 2})
        self.assertEqual(res_page2.status_code, 200)
        self.assertEqual(len(res_page2.get_json()['items']), 1)

    def test_08_invalid_assigned_user_value_rejected(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 'abc'})
        self.assertEqual(res.status_code, 400)
        self.assertEqual(res.get_json()['error'], 'invalid_input')

    def test_09_restricted_user_cannot_broaden_visibility_with_other_employee(self):
        self.login_as('assignedfilter_restricted', 53001)
        res = self._get_leads({'assigned_user_id': 53007})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 0)
        self.assertEqual(data['items'], [])

    def test_10_restricted_user_own_employee_filter_is_still_narrowed(self):
        self.login_as('assignedfilter_restricted', 53001)

        self._insert_lead(
            9110,
            'Assigned Filter Own',
            '111010',
            'WALK_IN',
            'NEW',
            53001,
            53001
        )

        res = self._get_leads({'assigned_user_id': 53001})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual([row['id'] for row in data['items']], [9110])
        self.assertEqual(data['total'], 1)

    def test_11_crm_all_leads_user_filters_across_employees(self):
        self.login_as('assignedfilter_all', 53002)
        res = self._get_leads({'assigned_user_id': 53007})
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(
            sorted(row['id'] for row in data['items']),
            [9103, 9106]
        )

    def test_12_rino_and_super_admin_bypass_remain_intact(self):
        self.login_as('rino', 2)
        self.assertEqual(self._get_leads({'assigned_user_id': 53007}).status_code, 200)

        self.login_as('assignedfilter_super', 53005)
        self.assertEqual(self._get_leads({'assigned_user_id': 53007}).status_code, 200)

    def test_13_filter_user_endpoint_is_read_only_and_assignment_endpoint_unchanged(self):
        self.login_as('assignedfilter_view', 53004)
        filter_users = self.client.get('/crm/filter-users')
        self.assertEqual(filter_users.status_code, 200)
        users = filter_users.get_json()
        self.assertTrue(users)
        self.assertTrue(all(sorted(item.keys()) == ['id', 'username'] for item in users))
        self.assertNotIn('email', users[0])
        self.assertNotIn('is_approved', users[0])

        denied_assign_users = self.client.get('/crm/users')
        self.assertIn(denied_assign_users.status_code, [302, 403])

    def test_14_filter_user_endpoint_available_to_crm_assign_user_too(self):
        self.login_as('assignedfilter_assign', 53003)
        res = self.client.get('/crm/filter-users')
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        usernames = [item['username'] for item in data]
        self.assertIn('assignedfilter_emp_a', usernames)
        self.assertIn('assignedfilter_emp_b', usernames)

    def test_15_dashboard_renders_assigned_to_filter_and_js_hooks(self):
        self.login_as('assignedfilter_view', 53004)
        res = self.client.get('/crm/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Assigned To', res.data)
        self.assertIn(b'assignedUserFilter', res.data)
        self.assertIn(b'All Employees', res.data)
        self.assertIn(b'Unassigned', res.data)

        js_text = (Path(__file__).resolve().parent / 'system_app/static/js/crm_leads.js').read_text(encoding='utf-8')
        self.assertIn('assignedUserFilterValue', js_text)
        self.assertIn('assignedUserSelect', js_text)
        self.assertIn('loadAssignedUserOptions()', js_text)
        self.assertIn('assigned_user_id', js_text)
        self.assertIn('currentPage = 1', js_text)

    def test_16_bulk_assign_behavior_remains_unchanged(self):
        self.login_as('assignedfilter_view', 53004)
        denied = self.client.post('/crm/leads/bulk-assign', json={"lead_ids": [9101], "user_id": 53006})
        self.assertIn(denied.status_code, [302, 403])


if __name__ == '__main__':
    unittest.main()
