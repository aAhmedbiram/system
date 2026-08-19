from datetime import datetime, timedelta
from pathlib import Path
import unittest

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.crm import services
from system_app.crm.services import CAIRO_TZ


class TestCRMBulkPhaseC(unittest.TestCase):
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
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBC %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbc_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',            'rino@test.com',    'pwd', TRUE, '{}'),
            (48001, 'pbc_view',        'view@test.com',    'pwd', TRUE, '{"crm_view": true}'),
            (48002, 'pbc_create',      'create@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (48003, 'pbc_create_only', 'create2@test.com', 'pwd', TRUE, '{"crm_create": true}'),
            (48004, 'pbc_assign',      'assign@test.com',  'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true}'),
            (48005, 'pbc_none',        'none@test.com',    'pwd', TRUE, '{}'),
            (48011, 'pbc_emp_a',       'a@test.com',       'pwd', TRUE, '{}'),
            (48012, 'pbc_emp_b',       'b@test.com',       'pwd', TRUE, '{}'),
            (48013, 'pbc_emp_c',       'c@test.com',       'pwd', TRUE, '{}')
        """, commit=True)

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBC %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbc_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member(self, member_id, name, end_date='2099-01-01', phone=None, email=None, package='Gold', status='VAL'):
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
            phone or f"08{member_id}",
            email or f"pbc{member_id}@example.com",
            None, None, None, None, None, end_date,
            package, None, status, 0, None, None
        ), commit=True)

    def _active_lead(self, lead_id, member_id, stage='NEW', archived=False):
        member = query_db("SELECT name, phone, email FROM members WHERE id = %s", (member_id,), one=True)
        query_db("""
            INSERT INTO crm_leads (
                id, member_id, name, phone, email, source, stage, created_by_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, %s, 'PBC_SOURCE', %s, %s, %s)
        """, (
            lead_id,
            member_id,
            member['name'],
            member['phone'],
            member['email'],
            stage,
            48002,
            archived,
        ), commit=True)

    def _preview(self, payload):
        return self.client.post('/crm/leads/bulk/preview', json=payload)

    def _execute(self, token):
        return self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})

    def _page(self, token=None):
        if token:
            return self.client.get('/crm/leads/bulk', query_string={'preview_token': token})
        return self.client.get('/crm/leads/bulk')

    def test_01_dashboard_bulk_link_visible_with_create_and_hidden_without_create(self):
        self.login_as('pbc_view', 48001)
        res_view = self.client.get('/crm/')
        self.assertEqual(res_view.status_code, 200)
        self.assertNotIn(b'/crm/leads/bulk', res_view.data)

        self.login_as('pbc_create', 48002)
        res_create = self.client.get('/crm/')
        self.assertEqual(res_create.status_code, 200)
        self.assertIn(b'/crm/leads/bulk', res_create.data)
        self.assertIn(b'Bulk Leads', res_create.data)

    def test_02_bulk_page_accessible_with_create_only(self):
        self.login_as('pbc_create_only', 48003)
        res = self._page()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Bulk CRM Leads', res.data)
        self.assertIn(b'Member Selection', res.data)
        self.assertIn(b'Preview Distribution', res.data)
        self.assertNotIn(b'previewTokenInput', res.data)

    def test_03_member_list_permission_and_pagination(self):
        self.login_as('pbc_none', 48005)
        denied = self.client.get('/crm/leads/bulk/members')
        self.assertIn(denied.status_code, [302, 403])

        self.login_as('pbc_create_only', 48003)
        for member_id in range(6001, 6056):
            self._member(member_id, f'PBC Member {member_id}')

        page1 = self.client.get('/crm/leads/bulk/members', query_string={'page': 1, 'per_page': 50})
        self.assertEqual(page1.status_code, 200)
        data1 = page1.get_json()
        self.assertEqual(data1['total_count'], 55)
        self.assertEqual(data1['page'], 1)
        self.assertEqual(len(data1['items']), 50)
        first = data1['items'][0]
        self.assertIn('id', first)
        self.assertIn('name', first)
        self.assertIn('phone', first)
        self.assertIn('membership_packages', first)
        self.assertIn('end_date', first)
        self.assertIn('membership_status', first)
        self.assertIn('has_active_crm_lead', first)

        page2 = self.client.get('/crm/leads/bulk/members', query_string={'page': 2, 'per_page': 50})
        self.assertEqual(page2.status_code, 200)
        data2 = page2.get_json()
        self.assertEqual(data2['total_count'], 55)
        self.assertEqual(data2['page'], 2)
        self.assertEqual(len(data2['items']), 5)

    def test_04_member_search_and_expiry_buckets(self):
        self.login_as('pbc_create_only', 48003)
        today = get_cairo_date()
        self._member(6101, 'PBC Search Alpha', (today + timedelta(days=3)).isoformat(), phone='0100006101')
        self._member(6102, 'PBC Search Beta', (today + timedelta(days=10)).isoformat(), phone='0100006102')
        self._member(6103, 'PBC Search Gamma', (today + timedelta(days=20)).isoformat(), phone='0100006103')
        self._member(6104, 'PBC Search Delta', (today - timedelta(days=2)).isoformat(), phone='0100006104')
        self._member(6105, 'PBC Search July 2025', '2025-07-15', phone='0100006105')
        self._member(6106, 'PBC Search July 2026', '2026-07-15', phone='0100006106')
        self._member(6107, 'PBC Search July 2026 DT', '2026-07-15 00:00:00', phone='0100006107')
        self._member(6108, 'PBC Search September 2026', '2026-09-25', phone='0100006108')
        self._member(6109, 'PBC Search September 2026 Late', '2026-09-28', phone='0100006109')
        self._member(6110, 'PBC Search Blank End', '   ', phone='0100006110')
        self._member(6111, 'PBC Search Invalid End', 'not-a-date', phone='0100006111')

        by_name = self.client.get('/crm/leads/bulk/members', query_string={'search_name': 'Alpha'})
        self.assertEqual([row['id'] for row in by_name.get_json()['items']], [6101])

        by_phone = self.client.get('/crm/leads/bulk/members', query_string={'search_phone': '0100006102'})
        self.assertEqual([row['id'] for row in by_phone.get_json()['items']], [6102])

        by_id = self.client.get('/crm/leads/bulk/members', query_string={'search_id': '6103'})
        self.assertIn(6103, [row['id'] for row in by_id.get_json()['items']])

        bucket_7 = self.client.get('/crm/leads/bulk/members', query_string={'expires_within': '7'})
        self.assertEqual([row['id'] for row in bucket_7.get_json()['items']], [6101])

        bucket_14 = self.client.get('/crm/leads/bulk/members', query_string={'expires_within': '14'})
        self.assertEqual([row['id'] for row in bucket_14.get_json()['items']], [6102])

        bucket_30 = self.client.get('/crm/leads/bulk/members', query_string={'expires_within': '30'})
        self.assertEqual([row['id'] for row in bucket_30.get_json()['items']], [6103])

        by_month = self.client.get('/crm/leads/bulk/members', query_string={'expires_month': '7', 'view': 'all', 'per_page': 50})
        self.assertEqual([row['id'] for row in by_month.get_json()['items']], [6105, 6106, 6107])

        by_year = self.client.get('/crm/leads/bulk/members', query_string={'expires_year': '2026', 'view': 'all', 'per_page': 50})
        self.assertEqual(
            [row['id'] for row in by_year.get_json()['items']],
            [6101, 6102, 6103, 6104, 6106, 6107, 6108, 6109]
        )

        by_month_year = self.client.get(
            '/crm/leads/bulk/members',
            query_string={'expires_month': '7', 'expires_year': '2026', 'view': 'all', 'per_page': 50}
        )
        self.assertEqual([row['id'] for row in by_month_year.get_json()['items']], [6106, 6107])

        by_month_year_bucket = self.client.get(
            '/crm/leads/bulk/members',
            query_string={
                'expires_month': '9',
                'expires_year': '2026',
                'expires_within': '30',
                'view': 'all',
                'per_page': 50
            }
        )
        self.assertEqual([row['id'] for row in by_month_year_bucket.get_json()['items']], [6103])

        ids_list = [row['id'] for row in by_month_year.get_json()['items']]
        preview = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "all", "expires_month": "7", "expires_year": "2026"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(preview.status_code, 200)
        snapshot = services.get_bulk_preview_snapshot(
            preview.get_json()['preview_token'],
            {"id": 48003, "username": "pbc_create_only"}
        )
        self.assertEqual(snapshot['selection']['selected_member_ids'], ids_list)
        self.assertEqual(snapshot['eligible_member_ids'], ids_list)

    def test_05_active_crm_indicator_and_preview_alignment(self):
        self.login_as('pbc_assign', 48004)
        self._member(6201, 'PBC Align A', '2099-01-01')
        self._member(6202, 'PBC Align B', '2099-01-01')
        self._member(6203, 'PBC Align C', '2099-01-01')
        self._active_lead(7202, 6202)

        listing = self.client.get('/crm/leads/bulk/members', query_string={'view': 'all'})
        rows = listing.get_json()['items']
        active_rows = [row for row in rows if row['has_active_crm_lead']]
        self.assertEqual([row['id'] for row in active_rows], [6202])

        preview = self._preview({
            "selection": {"mode": "filters", "filters": {"view": "all", "search_name": "PBC Align"}},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        data = preview.get_json()
        self.assertEqual(data['selected_count'], 3)
        self.assertEqual(data['eligible_count'], 2)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 1)

        snapshot = services.get_bulk_preview_snapshot(
            data['preview_token'],
            {"id": 48004, "username": "pbc_assign"}
        )
        self.assertEqual(snapshot['selection']['mode'], 'filters')
        self.assertEqual(snapshot['selected_count'], 3)
        self.assertEqual(snapshot['assignment_plan'], [
            {"member_id": 6201, "user_id": None},
            {"member_id": 6203, "user_id": None}
        ])

    def test_06_ui_hooks_rendered_without_manual_token_input(self):
        self.login_as('pbc_create_only', 48003)
        res = self._page()
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'bulkLeadsWorkspace', res.data)
        self.assertIn(b'bulkMembersTable', res.data)
        self.assertIn(b'bulkSearchId', res.data)
        self.assertIn(b'bulkSearchName', res.data)
        self.assertIn(b'bulkSearchPhone', res.data)
        self.assertIn(b'bulkViewFilter', res.data)
        self.assertIn(b'bulkExpiresWithin', res.data)
        self.assertIn(b'bulkExpiresMonth', res.data)
        self.assertIn(b'bulkExpiresYear', res.data)
        self.assertIn(b'selectFilteredBtn', res.data)
        self.assertIn(b'confirmBulkBtn', res.data)
        self.assertNotIn(b'previewTokenInput', res.data)
        js_source = Path(__file__).resolve().parent / 'system_app/static/js/crm_bulk_leads.js'
        js_text = js_source.read_text(encoding='utf-8')
        self.assertIn('bulkExpiresMonth', js_text)
        self.assertIn('bulkExpiresYear', js_text)
        self.assertIn('currentFilters()', js_text)
        self.assertIn('wireFilterChangeHandlers()', js_text)

    def test_07_explicit_ids_preview_from_ui_payload(self):
        self.login_as('pbc_create_only', 48003)
        self._member(6301, 'PBC Explicit 1', '2099-01-01')
        self._member(6302, 'PBC Explicit 2', '2099-01-01')
        self._member(6303, 'PBC Explicit 3', '2099-01-01')

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [6301, 6302, 6303]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['selected_count'], 3)
        self.assertEqual(data['eligible_count'], 3)
        self.assertEqual(data['distribution'], [])
        self.assertTrue(data['preview_token'])

    def test_08_filtered_preview_freezes_member_ids(self):
        self.login_as('pbc_create_only', 48003)
        self._member(6401, 'PBC Filter Freeze A', '2099-01-01')
        self._member(6402, 'PBC Filter Freeze B', '2099-01-01')
        self._member(6403, 'PBC Filter Freeze C', '2099-01-01')
        self._active_lead(7402, 6402)

        res = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "all", "search_name": "PBC Filter Freeze"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        token = res.get_json()['preview_token']
        snapshot = services.get_bulk_preview_snapshot(token, {"id": 48003, "username": "pbc_create_only"})
        self.assertEqual(snapshot['selection']['mode'], 'filters')
        self.assertEqual(snapshot['selection']['selected_member_ids'], [6401, 6402, 6403])
        self.assertEqual(snapshot['eligible_member_ids'], [6401, 6403])
        self.assertEqual(snapshot['skipped_count'], 1)

    def test_09_equal_and_unassigned_preview_permissions(self):
        self.login_as('pbc_create_only', 48003)
        self._member(6501, 'PBC Equal Gate A', '2099-01-01')
        self._member(6502, 'PBC Equal Gate B', '2099-01-01')
        unassigned = self._preview({
            "selection": {"mode": "ids", "member_ids": [6501, 6502]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(unassigned.status_code, 200)

        equal_blocked = self._preview({
            "selection": {"mode": "ids", "member_ids": [6501, 6502]},
            "distribution": {"mode": "equal", "user_ids": [48011, 48012]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(equal_blocked.status_code, 403)

        self.login_as('pbc_assign', 48004)
        equal_ok = self._preview({
            "selection": {"mode": "ids", "member_ids": [6501, 6502]},
            "distribution": {"mode": "equal", "user_ids": [48013, 48011, 48012]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(equal_ok.status_code, 200)
        data = equal_ok.get_json()
        self.assertEqual([row['lead_count'] for row in data['distribution']], [1, 1, 0])

    def test_10_preview_reload_wrong_owner_and_expired(self):
        self.login_as('pbc_assign', 48004)
        self._member(6601, 'PBC Preview Owner', '2099-01-01')
        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [6601]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = res.get_json()['preview_token']

        same_user_page = self._page(token)
        self.assertEqual(same_user_page.status_code, 200)
        self.assertIn(b'Preview Ready', same_user_page.data)
        self.assertIn(b'Confirm &amp; Create Leads', same_user_page.data)

        self.login_as('pbc_create_only', 48003)
        wrong_owner_page = self._page(token)
        self.assertEqual(wrong_owner_page.status_code, 200)
        self.assertIn(b'does not belong to the current user', wrong_owner_page.data)
        self.assertNotIn(b'PBC Preview Owner', wrong_owner_page.data)

        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        # Restore the preview owner before testing expiry.
        # Ownership validation intentionally happens before expiry validation.
        self.login_as('pbc_assign', 48004)

        expired_page = self._page(token)
        self.assertEqual(expired_page.status_code, 200)
        self.assertIn(b'Bulk preview token has expired', expired_page.data)
        self.assertIn(b'expired', expired_page.data.lower())

    def test_11_completed_preview_reload_shows_completed_summary(self):
        self.login_as('pbc_assign', 48004)
        self._member(6701, 'PBC Completed A', '2099-01-01')
        self._member(6702, 'PBC Completed B', '2099-01-01')
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [6701, 6702]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = preview.get_json()['preview_token']
        execute = self._execute(token)
        self.assertEqual(execute.status_code, 200)

        completed_page = self._page(token)
        self.assertEqual(completed_page.status_code, 200)
        self.assertIn(b'Completed', completed_page.data)
        self.assertIn(b'Created', completed_page.data)

    def test_12_execute_endpoint_accepts_preview_token_payload(self):
        self.login_as('pbc_assign', 48004)
        self._member(6801, 'PBC Execute A', '2099-01-01')
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [6801]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = preview.get_json()['preview_token']
        execute = self._execute(token)
        self.assertEqual(execute.status_code, 200)
        data = execute.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['status'], 'COMPLETED')

    def test_13_500_member_distribution_math(self):
        eligible_member_ids = list(range(7001, 7501))
        assignable_users = [
            {"id": 48011, "username": "pbc_emp_a"},
            {"id": 48012, "username": "pbc_emp_b"},
            {"id": 48013, "username": "pbc_emp_c"},
        ]
        plan = services._build_assignment_plan(eligible_member_ids, 'equal', assignable_users)
        counts = {}
        for row in plan:
            counts[row['user_id']] = counts.get(row['user_id'], 0) + 1
        self.assertEqual(len(plan), 500)
        self.assertEqual(counts[48011], 167)
        self.assertEqual(counts[48012], 167)
        self.assertEqual(counts[48013], 166)

    def test_14_selection_and_execution_end_to_end_subset(self):
        self.login_as('pbc_assign', 48004)
        self._member(6901, 'PBC Flow A', '2099-01-01')
        self._member(6902, 'PBC Flow B', '2099-01-01')
        self._member(6903, 'PBC Flow C', '2099-01-01')
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [6901, 6902, 6903]},
            "distribution": {"mode": "equal", "user_ids": [48013, 48011, 48012]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(preview.status_code, 200)
        preview_data = preview.get_json()
        self.assertEqual([row['lead_count'] for row in preview_data['distribution']], [1, 1, 1])

        execute = self._execute(preview_data['preview_token'])
        self.assertEqual(execute.status_code, 200)
        self.assertEqual(execute.get_json()['created'], 3)

        leads = query_db(
            "SELECT member_id, assigned_user_id, source, created_by_user_id FROM crm_leads WHERE member_id = ANY(%s) ORDER BY member_id ASC",
            ([6901, 6902, 6903],)
        ) or []
        self.assertEqual(len(leads), 3)
        self.assertEqual([row['source'] for row in leads], ['EXISTING_MEMBER', 'EXISTING_MEMBER', 'EXISTING_MEMBER'])

    def test_15_active_lead_members_not_duplicated(self):
        self.login_as('pbc_assign', 48004)
        self._member(6951, 'PBC Skip A', '2099-01-01')
        self._member(6952, 'PBC Skip B', '2099-01-01')
        self._active_lead(7452, 6952)
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [6951, 6952]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(preview.status_code, 200)
        data = preview.get_json()
        self.assertEqual(data['selected_count'], 2)
        self.assertEqual(data['eligible_count'], 1)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 1)

    def test_16_page_has_server_rendered_preview_hooks(self):
        self.login_as('pbc_assign', 48004)
        self._member(6961, 'PBC Rendered A', '2099-01-01')
        preview = self._preview({
            "selection": {"mode": "ids", "member_ids": [6961]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        token = preview.get_json()['preview_token']
        res = self._page(token)
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Preview Ready', res.data)
        self.assertIn(b'Confirm &amp; Create Leads', res.data)
        self.assertIn(b'Preview Token', res.data)


if __name__ == '__main__':
    unittest.main()
