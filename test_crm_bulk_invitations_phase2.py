from datetime import datetime, timedelta
import unittest

from system_app.app import app
from system_app.queries import query_db
from system_app.crm import services
from system_app.crm.services import CAIRO_TZ


class TestCRMBulkInvitationsPhase2(unittest.TestCase):
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
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE id = %s OR name LIKE %s", (70001, "PBI2 %"), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbi2_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',        'rino@test.com',   'pwd', TRUE, '{}'),
            (52001, 'pbi2_bulk',   'bulk@test.com',   'pwd', TRUE, '{"crm_bulk_leads": true}'),
            (52002, 'pbi2_assign', 'assign@test.com', 'pwd', TRUE, '{"crm_bulk_leads": true, "crm_assign": true}'),
            (52003, 'pbi2_view',   'view@test.com',   'pwd', TRUE, '{"crm_view": true}'),
            (52004, 'pbi2_super',  'super@test.com',  'pwd', TRUE, '{"super_admin": true}'),
            (52005, 'pbi2_none',   'none@test.com',   'pwd', TRUE, '{}')
        """, commit=True)
        self._member(70001, 'PBI2 Inviter', '01099999888')

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM crm_bulk_lead_operations", commit=True)
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE id = %s OR name LIKE %s", (70001, "PBI2 %"), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbi2_%", "rino"),
            commit=True
        )
        app.config['TESTING'] = self._old_testing
        app.config['SECRET_KEY'] = self._old_secret_key
        app.config['WTF_CSRF_ENABLED'] = self._old_csrf_enabled

    def login_as(self, username, user_id):
        with self.client.session_transaction() as sess:
            sess['user_id'] = user_id
            sess['username'] = username

    def _member(self, member_id, name, phone):
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
            phone,
            f"pbi2{member_id}@example.com",
            None, None, None, None, None, '2099-12-31',
            'Gold', None, 'VAL', 0, None, None
        ), commit=True)

    def _invitation(self, invitation_id, friend_name, friend_phone, used_date,
                    used_by='basmallah', inviter_member_id=70001, inviter_name='PBI2 Inviter'):
        query_db("""
            INSERT INTO invitations (
                id, member_id, member_name, friend_name, friend_phone, friend_email,
                used_date, used_by
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            invitation_id,
            inviter_member_id,
            inviter_name,
            friend_name,
            friend_phone,
            f"{friend_name.lower().replace(' ', '')}@example.com" if friend_name else None,
            used_date,
            used_by
        ), commit=True)

    def _member_preview(self, member_ids, distribution, user, username='pbi2_bulk'):
        self.login_as(username, user)
        return self.client.post('/crm/leads/bulk/preview', json={
            "selection": {"mode": "ids", "member_ids": member_ids},
            "distribution": distribution,
            "source": "EXISTING_MEMBER"
        })

    def _invitation_preview(self, selection, distribution, username='pbi2_bulk', user_id=52001):
        self.login_as(username, user_id)
        return self.client.post('/crm/leads/bulk/preview', json={
            "selection": selection,
            "distribution": distribution,
            "source": "INVITATIONS"
        })

    def _list_candidates(self, params=None):
        return self.client.get('/crm/leads/bulk/invitations', query_string=params or {})

    def test_01_preview_accepts_invitation_source_and_rejects_unsupported_source(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1001, 'Seif Alpha', '01012345678', datetime(2026, 8, 1, 10, 0, 0))

        res = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Seif"}},
            {"mode": "unassigned"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['source'], 'INVITATIONS')
        self.assertTrue(data['preview_token'])
        self.assertEqual(data['selected_count'], 1)
        self.assertEqual(data['eligible_count'], 1)
        self.assertEqual(data['distribution'], [])
        self.assertEqual(data['candidates'][0]['candidate_key'], '01012345678')
        self.assertEqual(data['candidates'][0]['invitation_id'], 1001)

        invalid = self.client.post('/crm/leads/bulk/preview', json={
            "selection": {"mode": "filters", "filters": {"search_name": "Seif"}},
            "distribution": {"mode": "unassigned"},
            "source": "WALK_IN"
        })
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()['error'], 'invalid_source')

    def test_02_explicit_candidate_keys_dedup_missing_and_invalid(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1101, 'Old Alpha', '01022334455', datetime(2026, 8, 1, 8, 0, 0))
        self._invitation(1102, 'New Alpha', '01022334455', datetime(2026, 8, 2, 8, 0, 0))
        self._invitation(1103, 'Blocked Beta', '01033445566', datetime(2026, 8, 2, 9, 0, 0))
        self._member(8101, 'PBI2 Member Block', '01033445566')

        res = self._invitation_preview(
            {"mode": "ids", "candidate_keys": ["01022334455", "01022334455", "01033445566", "01099999999"]},
            {"mode": "unassigned"}
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['selected_count'], 1)
        self.assertEqual(data['eligible_count'], 1)
        self.assertEqual(data['missing_count'], 2)
        self.assertEqual(data['skipped_reasons']['candidate_missing'], 2)
        self.assertEqual(data['candidates'][0]['invitation_id'], 1102)
        self.assertEqual(data['selected_candidate_keys'], ['01022334455'])
        self.assertCountEqual(data['missing_candidate_keys'], ['01033445566', '01099999999'])

        invalid = self._invitation_preview(
            {"mode": "ids", "candidate_keys": ["12345"]},
            {"mode": "unassigned"}
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()['error'], 'invalid_selection')

    def test_03_filters_match_listing_and_preview_freezes_snapshot(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1201, 'Filter Alpha', '01044445555', datetime(2026, 8, 3, 8, 0, 0), used_by='operator_a')
        self._invitation(1202, 'Filter Beta', '01044446666', datetime(2026, 7, 3, 8, 0, 0), used_by='operator_b')
        self._invitation(1203, 'Other Alpha', '01044447777', datetime(2026, 8, 4, 8, 0, 0), used_by='operator_a')

        listing = self._list_candidates({
            'search_name': 'Filter',
            'used_by': 'operator_a',
            'invitation_month': '8',
            'invitation_year': '2026'
        })
        self.assertEqual(listing.status_code, 200)
        listing_data = listing.get_json()
        self.assertEqual(listing_data['total'], 1)
        self.assertEqual([row['candidate_key'] for row in listing_data['items']], ['01044445555'])

        preview = self._invitation_preview(
            {
                "mode": "filters",
                "filters": {
                    'search_name': 'Filter',
                    'used_by': 'operator_a',
                    'invitation_month': '8',
                    'invitation_year': '2026'
                }
            },
            {"mode": "unassigned"}
        )
        self.assertEqual(preview.status_code, 200)
        preview_data = preview.get_json()
        self.assertEqual(preview_data['selected_count'], 1)
        self.assertEqual(preview_data['eligible_count'], 1)
        self.assertEqual(preview_data['selected_candidate_keys'], ['01044445555'])
        token = preview_data['preview_token']
        snapshot = services.get_bulk_preview_snapshot(token, {"id": 52001, "username": "pbi2_bulk"})
        self.assertEqual(snapshot['source'], 'INVITATIONS')
        self.assertEqual(snapshot['selection']['mode'], 'filters')
        self.assertEqual(snapshot['selection']['selected_candidate_keys'], ['01044445555'])
        self.assertEqual(snapshot['eligible_candidate_keys'], ['01044445555'])
        self.assertEqual(snapshot['candidates'][0]['invitation_id'], 1201)

        self._invitation(1204, 'Filter Gamma', '01044448888', datetime(2026, 8, 5, 8, 0, 0), used_by='operator_a')
        refreshed = services.get_bulk_preview_snapshot(token, {"id": 52001, "username": "pbi2_bulk"})
        self.assertEqual(refreshed['selection']['selected_candidate_keys'], ['01044445555'])
        self.assertEqual(refreshed['eligible_candidate_keys'], ['01044445555'])

    def test_04_filters_apply_before_dedupe(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1301, 'July Canonical', '01055556666', datetime(2026, 7, 4, 8, 0, 0), used_by='ops')
        self._invitation(1302, 'August Newer', '01055556666', datetime(2026, 8, 4, 8, 0, 0), used_by='ops')

        listing = self._list_candidates({'invitation_month': '7', 'invitation_year': '2026'})
        self.assertEqual(listing.status_code, 200)
        self.assertEqual([row['invitation_id'] for row in listing.get_json()['items']], [1301])

        preview = self._invitation_preview(
            {"mode": "filters", "filters": {"invitation_month": "7", "invitation_year": "2026"}},
            {"mode": "unassigned"}
        )
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.get_json()['selected_candidate_keys'], ['01055556666'])
        snapshot = services.get_bulk_preview_snapshot(
            preview.get_json()['preview_token'],
            {"id": 52001, "username": "pbi2_bulk"}
        )
        self.assertEqual(snapshot['candidates'][0]['invitation_id'], 1301)

    def test_05_distribution_math_permission_and_invalid_employee_checks(self):
        self.login_as('pbi2_bulk', 52001)
        for idx in range(1401, 1406):
            self._invitation(idx, f'Equal {idx}', f'0106666{idx - 1400:04d}', datetime(2026, 8, 6, 8, 0, 0))

        unassigned = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Equal"}},
            {"mode": "unassigned"}
        )
        self.assertEqual(unassigned.status_code, 200)
        self.assertEqual(unassigned.get_json()['distribution'], [])

        denied = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Equal"}},
            {"mode": "equal", "user_ids": [52002, 52001, 52004]},
            username='pbi2_bulk',
            user_id=52001
        )
        self.assertIn(denied.status_code, [302, 403])

        self.login_as('pbi2_assign', 52002)
        equal = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Equal"}},
            {"mode": "equal", "user_ids": [52004, 52002, 52001]},
            username='pbi2_assign',
            user_id=52002
        )
        self.assertEqual(equal.status_code, 200)
        data = equal.get_json()
        self.assertEqual([row['user_id'] for row in data['distribution']], [52001, 52002, 52004])
        self.assertEqual([row['lead_count'] for row in data['distribution']], [2, 2, 1])
        snapshot = services.get_bulk_preview_snapshot(data['preview_token'], {"id": 52002, "username": "pbi2_assign"})
        self.assertEqual(
            snapshot['assignment_plan'],
            [
                {"candidate_key": "01066660005", "user_id": 52001},
                {"candidate_key": "01066660004", "user_id": 52001},
                {"candidate_key": "01066660003", "user_id": 52002},
                {"candidate_key": "01066660002", "user_id": 52002},
                {"candidate_key": "01066660001", "user_id": 52004},
            ]
        )

        invalid = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Equal"}},
            {"mode": "equal", "user_ids": [52002, 999999]},
            username='pbi2_assign',
            user_id=52002
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(invalid.get_json()['error'], 'invalid_employee')

    def test_06_durable_operation_and_snapshot_source(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1501, 'Durable One', '01077778888', datetime(2026, 8, 8, 8, 0, 0))
        before_ops = query_db("SELECT COUNT(*) AS count FROM crm_bulk_lead_operations", one=True)['count']
        before_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']
        before_activities = query_db("SELECT COUNT(*) AS count FROM crm_activities", one=True)['count']
        before_invitations = query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count']

        res = self._invitation_preview(
            {"mode": "ids", "candidate_keys": ["01077778888"]},
            {"mode": "unassigned"}
        )
        self.assertEqual(res.status_code, 200)
        token = res.get_json()['preview_token']
        after_ops = query_db("SELECT COUNT(*) AS count FROM crm_bulk_lead_operations", one=True)['count']
        self.assertEqual(after_ops, before_ops + 1)
        self.assertEqual(before_leads, query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count'])
        self.assertEqual(before_activities, query_db("SELECT COUNT(*) AS count FROM crm_activities", one=True)['count'])
        self.assertEqual(before_invitations, query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count'])

        operation = query_db(
            "SELECT token, status, snapshot FROM crm_bulk_lead_operations WHERE token = %s",
            (token,),
            one=True
        )
        self.assertIsNotNone(operation)
        self.assertEqual(operation['status'], 'PREVIEW')
        self.assertEqual(operation['snapshot']['source'], 'INVITATIONS')
        self.assertEqual(operation['snapshot']['candidates'][0]['candidate_key'], '01077778888')

    def test_07_token_ownership_expiry_and_existing_member_reload(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1601, 'Ownership One', '01088889999', datetime(2026, 8, 9, 8, 0, 0))
        preview = self._invitation_preview(
            {"mode": "ids", "candidate_keys": ["01088889999"]},
            {"mode": "unassigned"}
        )
        token = preview.get_json()['preview_token']

        snapshot = services.get_bulk_preview_snapshot(token, {"id": 52001, "username": "pbi2_bulk"})
        self.assertEqual(snapshot['source'], 'INVITATIONS')
        self.assertEqual(snapshot['selection']['selected_candidate_keys'], ['01088889999'])

        with self.assertRaises(services.CRMForbiddenError):
            services.get_bulk_preview_snapshot(token, {"id": 52003, "username": "pbi2_view"})

        with self.assertRaises(services.CRMNotFoundError):
            services.get_bulk_preview_snapshot(token + 'tamper', {"id": 52001, "username": "pbi2_bulk"})

        query_db(
            "UPDATE crm_bulk_lead_operations SET expires_at = %s WHERE token = %s",
            (datetime.now(CAIRO_TZ) - timedelta(seconds=1), token),
            commit=True
        )
        with self.assertRaises(services.CRMNotFoundError):
            services.get_bulk_preview_snapshot(token, {"id": 52001, "username": "pbi2_bulk"})

        self.login_as('pbi2_assign', 52002)
        self._member(79101, 'PBI2 Existing Reload', '01011110000')
        member_preview = self.client.post('/crm/leads/bulk/preview', json={
            "selection": {"mode": "ids", "member_ids": [79101]},
            "distribution": {"mode": "unassigned"},
            "source": "EXISTING_MEMBER"
        })
        self.assertEqual(member_preview.status_code, 200)
        member_snapshot = services.get_bulk_preview_snapshot(
            member_preview.get_json()['preview_token'],
            {"id": 52002, "username": "pbi2_assign"}
        )
        self.assertEqual(member_snapshot['selection']['selected_member_ids'], [79101])

    def test_08_execute_creates_invitation_lead_and_preserves_invitations(self):
        self.login_as('pbi2_super', 52004)
        self._invitation(1701, 'Execute Guard', '01022223333', datetime(2026, 8, 10, 8, 0, 0))
        before_invitations = query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count']
        before_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']

        preview = self._invitation_preview(
            {"mode": "ids", "candidate_keys": ["01022223333"]},
            {"mode": "unassigned"},
            username='pbi2_super',
            user_id=52004
        )
        token = preview.get_json()['preview_token']

        execute = self.client.post('/crm/leads/bulk/execute', json={"preview_token": token})
        self.assertEqual(execute.status_code, 200)
        data = execute.get_json()
        self.assertEqual(data['created'], 1)
        self.assertEqual(data['skipped'], 0)
        self.assertEqual(data['failed'], 0)

        self.assertEqual(before_leads + 1, query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count'])
        self.assertEqual(before_invitations, query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count'])

    def test_09_repeated_preview_creates_independent_operations(self):
        self.login_as('pbi2_bulk', 52001)
        self._invitation(1801, 'Repeat One', '01033334444', datetime(2026, 8, 11, 8, 0, 0))

        first = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Repeat"}},
            {"mode": "unassigned"}
        )
        first_data = first.get_json()
        self.assertEqual(first_data['selected_count'], 1)

        self._invitation(1802, 'Repeat Two', '01033335555', datetime(2026, 8, 12, 8, 0, 0))
        second = self._invitation_preview(
            {"mode": "filters", "filters": {"search_name": "Repeat"}},
            {"mode": "unassigned"}
        )
        second_data = second.get_json()
        self.assertEqual(second_data['selected_count'], 2)
        self.assertNotEqual(first_data['preview_token'], second_data['preview_token'])


if __name__ == '__main__':
    unittest.main()
