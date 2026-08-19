from datetime import datetime, timedelta
from pathlib import Path
import unittest

from system_app.app import app
from system_app.func import get_cairo_date
from system_app.queries import query_db
from system_app.crm import services
from system_app.crm.permissions import get_current_user
from system_app.crm.services import CRMForbiddenError, CRMNotFoundError, CAIRO_TZ


class TestCRMBulkPhaseA(unittest.TestCase):
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
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBA %",), commit=True)
        query_db(
    "DELETE FROM users WHERE username LIKE %s OR username = %s",
    ("pba_%", "rino"),
    commit=True
)
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',        'rino@test.com', 'pwd', TRUE, '{}'),
            (45001, 'pba_create',  'create@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true}'),
            (45002, 'pba_assign',  'assign@test.com', 'pwd', TRUE, '{"crm_view": true, "crm_create": true, "crm_assign": true}'),
            (45005, 'pba_user_a',  'usera@test.com', 'pwd', TRUE, '{}'),
            (45011, 'pba_user_b',  'userb@test.com', 'pwd', TRUE, '{}'),
            (45003, 'pba_none',    'none@test.com', 'pwd', TRUE, '{}')
        """, commit=True)
    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBA %",), commit=True)
        query_db(
    "DELETE FROM users WHERE username LIKE %s OR username = %s",
    ("pba_%", "rino"),
    commit=True
)
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member_data(self, member_id, name, end_date, phone=None, email=None, **extra):
        data = {
            "id": member_id,
            "name": name,
            "phone": phone or f"01{member_id}",
            "email": email or f"pba{member_id}@example.com",
            "age": extra.get("age"),
            "gender": extra.get("gender"),
            "birthdate": extra.get("birthdate"),
            "actual_starting_date": extra.get("actual_starting_date"),
            "starting_date": extra.get("starting_date"),
            "end_date": end_date,
            "membership_packages": extra.get("membership_packages"),
            "membership_fees": extra.get("membership_fees"),
            "membership_status": extra.get("membership_status", "VAL"),
            "invitations": extra.get("invitations", 0),
            "comment": extra.get("comment"),
            "national_id": extra.get("national_id"),
        }
        query_db("""
            INSERT INTO members (
                id, name, phone, email, age, gender, birthdate,
                actual_starting_date, starting_date, end_date,
                membership_packages, membership_fees, membership_status,
                invitations, comment, national_id
            ) VALUES (
                %(id)s, %(name)s, %(phone)s, %(email)s, %(age)s, %(gender)s, %(birthdate)s,
                %(actual_starting_date)s, %(starting_date)s, %(end_date)s,
                %(membership_packages)s, %(membership_fees)s, %(membership_status)s,
                %(invitations)s, %(comment)s, %(national_id)s
            )
        """, data, commit=True)

    def _create_active_lead(self, lead_id, member_id, stage='NEW', archived=False, created_by_user_id=45001):
        member = query_db("SELECT name, phone, email FROM members WHERE id = %s", (member_id,), one=True)
        query_db("""
            INSERT INTO crm_leads (
                id, member_id, name, phone, email, source, stage,
                created_by_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, %s, 'PBA_SOURCE', %s, %s, %s)
        """, (
            lead_id,
            member_id,
            member['name'],
            member['phone'],
            member['email'],
            stage,
            created_by_user_id,
            archived,
        ), commit=True)

    def _preview(self, payload):
        return self.client.post('/crm/leads/bulk/preview', json=payload)

    def test_01_bulk_shell_requires_view_and_create(self):
        self.login_as('pba_none', 45003)
        res = self.client.get('/crm/leads/bulk')
        self.assertIn(res.status_code, [302, 403])

        self.login_as('pba_create', 45001)
        res_create_only = self.client.get('/crm/leads/bulk')
        self.assertEqual(res_create_only.status_code, 200)

        self.login_as('rino', 2)
        res_rino = self.client.get('/crm/leads/bulk')
        self.assertEqual(res_rino.status_code, 200)
        self.assertIn(b'Bulk CRM Leads', res_rino.data)
        self.assertIn(b'Bulk CRM Leads', res_rino.data)
        self.assertIn(b'Preview and Execution', res_rino.data)
        self.assertIn(b'Confirm &amp; Create Leads', res_rino.data)
        self.assertIn(b'csrf-token', res_rino.data)

    def test_02_preview_requires_create_permission(self):
        self.login_as('pba_none', 45003)
        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [1]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertIn(res.status_code, [302, 403])

    def test_03_ids_selection_dedup_missing_and_active_lead_exclusion(self):
        self.login_as('pba_create', 45001)
        self._member_data(8101, 'PBA Id Alpha', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        self._member_data(8102, 'PBA Id Beta', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        self._member_data(8103, 'PBA Id Gamma', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        self._member_data(8104, 'PBA Id Archived', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        self._create_active_lead(9103, 8103, stage='NEW')
        self._create_active_lead(9104, 8104, stage='NEW', archived=True)

        before_leads = query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)['count']
        before_activities = query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)['count']

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [8101, 8101, 8102, 999999, 8103, 8104]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['selected_count'], 4)
        self.assertEqual(data['eligible_count'], 3)
        self.assertEqual(data['missing_count'], 1)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 1)
        self.assertEqual(data['skipped_reasons']['member_missing'], 1)
        self.assertEqual(data['distribution'], [])
        self.assertTrue(data['preview_token'])
        self.assertEqual(before_leads, query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)['count'])
        self.assertEqual(before_activities, query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)['count'])

    def test_04_active_stage_matrix_and_nonblocking_terminal_states(self):
        self.login_as('pba_create', 45001)
        today = get_cairo_date()
        future = (today + timedelta(days=30)).isoformat()

        stage_rows = [
            (8201, 'PBA Stage NEW', 'NEW', False),
            (8202, 'PBA Stage CONTACTED', 'CONTACTED', False),
            (8203, 'PBA Stage FOLLOW_UP', 'FOLLOW_UP', False),
            (8204, 'PBA Stage INTERESTED', 'INTERESTED', False),
            (8205, 'PBA Stage TRIAL', 'TRIAL', False),
            (8206, 'PBA Stage WON', 'WON', False),
            (8207, 'PBA Stage LOST', 'LOST', False),
            (8208, 'PBA Stage Archived', 'NEW', True),
        ]
        for member_id, name, stage, archived in stage_rows:
            self._member_data(member_id, name, future, membership_packages='Silver', membership_fees=750)
            self._create_active_lead(9200 + member_id, member_id, stage=stage, archived=archived)

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [row[0] for row in stage_rows]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['selected_count'], 8)
        self.assertEqual(data['eligible_count'], 3)
        self.assertEqual(data['skipped_reasons']['active_lead_exists'], 5)

    def test_05_filters_search_and_expiry_buckets(self):
        self.login_as('pba_create', 45001)
        today = get_cairo_date()
        self._member_data(8301, 'PBA Filter Alpha', (today + timedelta(days=3)).isoformat(), membership_packages='Bronze', membership_fees=500)
        self._member_data(8302, 'PBA Filter Alpha Two', (today + timedelta(days=10)).isoformat(), membership_packages='Bronze', membership_fees=500)
        self._member_data(8303, 'PBA Filter Beta', (today - timedelta(days=2)).isoformat(), membership_packages='Bronze', membership_fees=500)
        self._member_data(8304, 'PBA Filter Gamma', (today + timedelta(days=20)).isoformat(), membership_packages='Bronze', membership_fees=500)
        self._member_data(8305, 'PBA Server Side One', (today + timedelta(days=20)).isoformat(), membership_packages='Bronze', membership_fees=500)
        self._member_data(8306, 'PBA Server Side Two', (today + timedelta(days=40)).isoformat(), membership_packages='Bronze', membership_fees=500)

        res_search = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "active", "search_name": "Filter Alpha"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_search.status_code, 200)
        self.assertEqual(res_search.get_json()['selected_count'], 2)

        res_active = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "active"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_active.status_code, 200)
        self.assertEqual(res_active.get_json()['selected_count'], 5)

        res_expired = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "expired"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_expired.status_code, 200)
        self.assertEqual(res_expired.get_json()['selected_count'], 1)

        res_7 = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "active", "expires_within": "7"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_7.status_code, 200)
        self.assertEqual(res_7.get_json()['selected_count'], 1)

        res_14 = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "active", "expires_within": "14"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_14.status_code, 200)
        self.assertEqual(res_14.get_json()['selected_count'], 1)

        res_30 = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "active", "expires_within": "30"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_30.status_code, 200)
        self.assertEqual(res_30.get_json()['selected_count'], 2)

        res_excluded = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "all", "search_name": "Server Side"},
                "excluded_member_ids": [8305]
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res_excluded.status_code, 200)
        self.assertEqual(res_excluded.get_json()['selected_count'], 1)

    def test_06_equal_distribution_math_and_employee_validation(self):
        self.login_as('pba_assign', 45002)
        for idx, member_id in enumerate(range(8401, 8406), start=1):
            self._member_data(member_id, f'PBA Equal {idx}', '2099-01-01', membership_packages='Platinum', membership_fees=1200)

        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [8401, 8402, 8403, 8404, 8405]},
            "distribution": {"mode": "equal", "user_ids": [45011, 45002, 45005]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual([row['user_id'] for row in data['distribution']], [45002, 45005, 45011])
        self.assertEqual([row['lead_count'] for row in data['distribution']], [2, 2, 1])

        duplicate_employee = self._preview({
            "selection": {"mode": "ids", "member_ids": [8401, 8402]},
            "distribution": {"mode": "equal", "user_ids": [45011, 45011, 45002]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(duplicate_employee.status_code, 200)
        self.assertEqual([row['user_id'] for row in duplicate_employee.get_json()['distribution']], [45002, 45011])

        invalid_employee = self._preview({
            "selection": {"mode": "ids", "member_ids": [8401, 8402]},
            "distribution": {"mode": "equal", "user_ids": [45002, 99999]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(invalid_employee.status_code, 400)
        invalid_data = invalid_employee.get_json()
        self.assertEqual(invalid_data['error'], 'invalid_employee')
        self.assertIn(99999, invalid_data['details']['user_ids'])

    def test_07_preview_token_scoped_and_expiring(self):
        self.login_as('pba_assign', 45002)
        self._member_data(8501, 'PBA Token Alpha', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        self._member_data(8502, 'PBA Token Beta', '2099-01-01', membership_packages='Gold', membership_fees=1000)
        res = self._preview({
            "selection": {"mode": "ids", "member_ids": [8501, 8502]},
            "distribution": {"mode": "equal", "user_ids": [45002, 45001]},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        token = data['preview_token']
        same_user_snapshot = services.get_bulk_preview_snapshot(
            token,
            {"id": 45002, "username": "pba_assign"}
        )
        self.assertEqual(
            same_user_snapshot['selection']['selected_member_ids'],
            [8501, 8502]
        )

        self.login_as('pba_none', 45003)
        with self.assertRaises(CRMForbiddenError):
            services.get_bulk_preview_snapshot(
                token,
                {"id": 45003, "username": "pba_none"}
            )

        with self.assertRaises(CRMNotFoundError):
            services.get_bulk_preview_snapshot(token + 'tamper', {"id": 45002, "username": "pba_assign"})

        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        self.login_as('pba_assign', 45002)
        with self.assertRaises(CRMNotFoundError):
            services.get_bulk_preview_snapshot(
                token,
                {"id": 45002, "username": "pba_assign"}
            )

    def test_08_unsupported_campaign_and_source_validation(self):
        self.login_as('pba_create', 45001)
        self._member_data(8601, 'PBA Campaign Member', '2099-01-01', membership_packages='Standard', membership_fees=600)

        before_leads = query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)['count']
        before_activities = query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)['count']

        unsupported_campaign = self._preview({
            "selection": {"mode": "ids", "member_ids": [8601]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER",
            "campaign_id": 123
        })
        self.assertEqual(unsupported_campaign.status_code, 400)
        self.assertEqual(unsupported_campaign.get_json()['error'], 'unsupported_campaign')

        invalid_source = self._preview({
            "selection": {"mode": "ids", "member_ids": [8601]},
            "distribution": {"mode": "unassigned"},
            "source": "WALK_IN"
        })
        self.assertEqual(invalid_source.status_code, 400)
        self.assertEqual(invalid_source.get_json()['error'], 'invalid_source')

        after_leads = query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)['count']
        after_activities = query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)['count']
        self.assertEqual(before_leads, after_leads)
        self.assertEqual(before_activities, after_activities)

    def test_09_expiry_month_year_filters_and_preview_alignment(self):
        self.login_as('pba_create', 45001)
        self._member_data(8701, 'PBA Expiry Jul 2025', '2025-07-15', membership_packages='Silver', membership_fees=700)
        self._member_data(8702, 'PBA Expiry Jul 2026', '2026-07-15', membership_packages='Silver', membership_fees=700)
        self._member_data(8703, 'PBA Expiry Jun 2026', '2026-06-15', membership_packages='Silver', membership_fees=700)
        self._member_data(8704, 'PBA Expiry Jul 2026 DT', '2026-07-15 00:00:00', membership_packages='Silver', membership_fees=700)
        self._member_data(8705, 'PBA Expiry Sep 2026', '2026-09-10', membership_packages='Silver', membership_fees=700)
        self._member_data(8706, 'PBA Expiry Sep 2026 Late', '2026-09-25', membership_packages='Silver', membership_fees=700)
        self._member_data(8707, 'PBA Expiry Blank', '   ', membership_packages='Silver', membership_fees=700)
        self._member_data(8708, 'PBA Expiry Invalid', 'not-a-date', membership_packages='Silver', membership_fees=700)

        month_only = self.client.get('/crm/leads/bulk/members', query_string={'expires_month': '7', 'view': 'all', 'per_page': 100})
        self.assertEqual(month_only.status_code, 200)
        self.assertEqual([row['id'] for row in month_only.get_json()['items']], [8701, 8702, 8704])

        year_only = self.client.get('/crm/leads/bulk/members', query_string={'expires_year': '2026', 'view': 'all', 'per_page': 100})
        self.assertEqual(year_only.status_code, 200)
        self.assertEqual([row['id'] for row in year_only.get_json()['items']], [8702, 8703, 8704, 8705, 8706])

        july_2026 = self.client.get(
            '/crm/leads/bulk/members',
            query_string={'expires_month': '7', 'expires_year': '2026', 'view': 'all', 'per_page': 100}
        )
        self.assertEqual(july_2026.status_code, 200)
        july_2026_ids = [row['id'] for row in july_2026.get_json()['items']]
        self.assertEqual(july_2026_ids, [8702, 8704])

        september_2026_within_30 = self.client.get(
            '/crm/leads/bulk/members',
            query_string={
                'expires_month': '9',
                'expires_year': '2026',
                'expires_within': '30',
                'view': 'all',
                'per_page': 100
            }
        )
        self.assertEqual(september_2026_within_30.status_code, 200)
        self.assertEqual([row['id'] for row in september_2026_within_30.get_json()['items']], [8705])

        preview = self._preview({
            "selection": {
                "mode": "filters",
                "filters": {"view": "all", "expires_month": "7", "expires_year": "2026"}
            },
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(preview.status_code, 200)
        preview_data = preview.get_json()
        self.assertEqual(preview_data['selected_count'], 2)
        self.assertEqual(preview_data['eligible_count'], 2)
        self.assertEqual(preview_data['distribution'], [])
        snapshot = services.get_bulk_preview_snapshot(
            preview_data['preview_token'],
            {"id": 45001, "username": "pba_create"}
        )
        self.assertEqual(snapshot['selection']['selected_member_ids'], july_2026_ids)
        self.assertEqual(snapshot['eligible_member_ids'], july_2026_ids)
        self.assertEqual(snapshot['selected_count'], 2)
