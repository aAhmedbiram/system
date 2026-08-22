from datetime import datetime
import unittest

from system_app.app import app
from system_app.queries import query_db


class TestCRMBulkInvitationsPhase1(unittest.TestCase):
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
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBI1 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbi1_%", "rino"),
            commit=True
        )
        query_db("""
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES
            (2,     'rino',         'rino@test.com',   'pwd', TRUE, '{}'),
            (51001, 'pbi1_bulk',    'bulk@test.com',   'pwd', TRUE, '{"crm_bulk_leads": true}'),
            (51002, 'pbi1_view',    'view@test.com',   'pwd', TRUE, '{"crm_view": true}'),
            (51003, 'pbi1_super',   'super@test.com',  'pwd', TRUE, '{"super_admin": true}'),
            (51004, 'pbi1_none',    'none@test.com',   'pwd', TRUE, '{}')
        """, commit=True)
        self._member(70001, 'PBI1 Inviter', '01099999888')

    def tearDown(self):
        query_db("DELETE FROM crm_activities", commit=True)
        query_db("DELETE FROM crm_leads", commit=True)
        query_db("DELETE FROM invitations", commit=True)
        query_db("DELETE FROM members WHERE name LIKE %s", ("PBI1 %",), commit=True)
        query_db(
            "DELETE FROM users WHERE username LIKE %s OR username = %s",
            ("pbi1_%", "rino"),
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
            f"pbi1{member_id}@example.com",
            None, None, None, None, None, "2099-12-31",
            "Gold", None, "VAL", 0, None, None
        ), commit=True)

    def _invitation(self, invitation_id, friend_name, friend_phone, used_date, used_by='bulk_user', inviter_member_id=70001, inviter_name='PBI1 Inviter'):
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

    def _active_lead(self, lead_id, phone, stage='NEW', archived=False, member_id=None):
        query_db("""
            INSERT INTO crm_leads (
                id, member_id, name, phone, source, stage,
                created_by_user_id, is_archived
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            lead_id,
            member_id,
            f"Lead {lead_id}",
            phone,
            "WALK_IN",
            stage,
            51001,
            archived
        ), commit=True)

    def _list(self, params=None):
        return self.client.get('/crm/leads/bulk/invitations', query_string=params or {})

    def test_01_permission_gate_and_bypass(self):
        self.login_as('pbi1_none', 51004)
        denied = self._list()
        self.assertIn(denied.status_code, [302, 403])

        self.login_as('pbi1_bulk', 51001)
        allowed = self._list()
        self.assertEqual(allowed.status_code, 200)
        self.assertIn(b'items', allowed.data)

        self.login_as('rino', 2)
        self.assertEqual(self._list().status_code, 200)

        self.login_as('pbi1_super', 51003)
        self.assertEqual(self._list().status_code, 200)

    def test_02_valid_invitations_only_and_invalid_phones_excluded(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(1001, 'Valid Alpha', ' 01012345678 ', datetime(2026, 7, 10, 10, 0, 0))
        self._invitation(1002, 'Null Phone', None, datetime(2026, 7, 10, 10, 5, 0))
        self._invitation(1003, 'Blank Phone', '   ', datetime(2026, 7, 10, 10, 6, 0))
        self._invitation(1004, 'Zero Phone', '0', datetime(2026, 7, 10, 10, 7, 0))
        self._invitation(1005, 'Zeros Phone', '00000000000', datetime(2026, 7, 10, 10, 8, 0))
        self._invitation(1006, 'Short Junk', '132456', datetime(2026, 7, 10, 10, 9, 0))
        self._invitation(1007, 'Text Junk', 'menria', datetime(2026, 7, 10, 10, 10, 0))

        res = self._list()
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(len(data['items']), 1)
        self.assertEqual(data['items'][0]['candidate_key'], '01012345678')
        self.assertEqual(data['items'][0]['invitation_id'], 1001)

    def test_03_duplicate_phone_dedup_and_newest_wins(self):
        self.login_as('pbi1_bulk', 51001)
        phone = '01022334455'
        self._invitation(1101, 'Dup Old', phone, datetime(2026, 7, 1, 9, 0, 0))
        self._invitation(1102, 'Dup New', phone, datetime(2026, 7, 2, 9, 0, 0))

        res = self._list()
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['items'][0]['invitation_id'], 1102)
        self.assertEqual(data['items'][0]['name'], 'Dup New')

    def test_04_equal_used_date_higher_id_wins(self):
        self.login_as('pbi1_bulk', 51001)
        phone = '01033445566'
        used = datetime(2026, 7, 3, 10, 0, 0)
        self._invitation(1201, 'Tie Old', phone, used)
        self._invitation(1202, 'Tie New', phone, used)

        res = self._list()
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 1)
        self.assertEqual(data['items'][0]['invitation_id'], 1202)
        self.assertEqual(data['items'][0]['name'], 'Tie New')

    def test_05_member_and_active_crm_exclusions(self):
        self.login_as('pbi1_bulk', 51001)
        member_phone = '01044556677'
        crm_phone = '01055667788'
        terminal_phone = '01066778899'
        archived_phone = '01077889900'

        self._member(6001, 'PBI1 Member Block', member_phone)
        self._active_lead(6101, crm_phone, stage='NEW')
        self._active_lead(6102, terminal_phone, stage='WON')
        self._active_lead(6103, archived_phone, stage='NEW', archived=True)

        self._invitation(1301, 'Member Block', member_phone, datetime(2026, 7, 4, 11, 0, 0))
        self._invitation(1302, 'CRM Block', crm_phone, datetime(2026, 7, 4, 11, 5, 0))
        self._invitation(1303, 'Terminal Allowed', terminal_phone, datetime(2026, 7, 4, 11, 10, 0))
        self._invitation(1304, 'Archived Allowed', archived_phone, datetime(2026, 7, 4, 11, 15, 0))

        res = self._list()
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertEqual(data['total'], 2)
        phones = [item['candidate_key'] for item in data['items']]
        self.assertIn(terminal_phone, phones)
        self.assertIn(archived_phone, phones)
        self.assertNotIn(member_phone, phones)
        self.assertNotIn(crm_phone, phones)

    def test_06_search_filters_and_used_by(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(1401, 'Alice Match', '01011112222', datetime(2026, 7, 5, 8, 0, 0), used_by='operator_a')
        self._invitation(1402, 'Bob Match', '01011113333', datetime(2026, 7, 5, 9, 0, 0), used_by='operator_b')

        by_name = self._list({'search_name': 'alice'})
        self.assertEqual(by_name.status_code, 200)
        self.assertEqual(by_name.get_json()['total'], 1)

        by_phone = self._list({'search_phone': '3333'})
        self.assertEqual(by_phone.status_code, 200)
        self.assertEqual(by_phone.get_json()['total'], 1)

        by_used_by = self._list({'used_by': 'operator_b'})
        self.assertEqual(by_used_by.status_code, 200)
        self.assertEqual(by_used_by.get_json()['total'], 1)
        self.assertEqual(by_used_by.get_json()['items'][0]['invitation_id'], 1402)

    def test_07_month_year_and_combination_filters(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(1501, 'July One', '01022223333', datetime(2026, 7, 6, 8, 0, 0))
        self._invitation(1502, 'July Two', '01022224444', datetime(2025, 7, 6, 8, 0, 0))
        self._invitation(1503, 'June 2026', '01022225555', datetime(2026, 6, 6, 8, 0, 0))
        self._invitation(1504, 'August 2026', '01022226666', datetime(2026, 8, 6, 8, 0, 0))

        july = self._list({'invitation_month': '7'})
        self.assertEqual(july.status_code, 200)
        self.assertEqual(july.get_json()['total'], 2)

        year_2026 = self._list({'invitation_year': '2026'})
        self.assertEqual(year_2026.status_code, 200)
        self.assertEqual(year_2026.get_json()['total'], 3)

        july_2026 = self._list({'invitation_month': '7', 'invitation_year': '2026'})
        self.assertEqual(july_2026.status_code, 200)
        self.assertEqual(july_2026.get_json()['total'], 1)
        self.assertEqual(july_2026.get_json()['items'][0]['invitation_id'], 1501)

    def test_08_filters_apply_before_dedupe(self):
        self.login_as('pbi1_bulk', 51001)
        phone = '01033334444'
        self._invitation(1601, 'July Canonical', phone, datetime(2026, 7, 6, 8, 0, 0))
        self._invitation(1602, 'August Newer', phone, datetime(2026, 8, 6, 8, 0, 0))

        july = self._list({'invitation_month': '7'})
        self.assertEqual(july.status_code, 200)
        self.assertEqual(july.get_json()['total'], 1)
        self.assertEqual(july.get_json()['items'][0]['invitation_id'], 1601)

    def test_09_pagination_total_is_deduplicated_and_deterministic(self):
        self.login_as('pbi1_bulk', 51001)
        for idx, day in enumerate([1, 2, 3, 4, 5], start=1):
            self._invitation(1700 + idx, f'Paged {idx}', f'0104444{idx:04d}', datetime(2026, 7, day, 8, 0, 0))

        page1 = self._list({'invitation_year': '2026'})
        self.assertEqual(page1.status_code, 200)
        data1 = page1.get_json()
        self.assertEqual(data1['total'], 5)
        self.assertEqual(data1['pages'], 1)
        self.assertEqual([item['invitation_id'] for item in data1['items']], [1705, 1704, 1703, 1702, 1701])

    def test_10_new_eligible_invitation_appears_on_next_request(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(1801, 'Recurring A', '01055556666', datetime(2026, 7, 7, 8, 0, 0))

        first = self._list({'search_name': 'Recurring'})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.get_json()['total'], 1)

        self._invitation(1802, 'Recurring B', '01055557777', datetime(2026, 7, 8, 8, 0, 0))
        second = self._list({'search_name': 'Recurring'})
        self.assertEqual(second.status_code, 200)
        self.assertEqual(second.get_json()['total'], 2)

    def test_11_endpoint_is_read_only(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(1901, 'Read Only', '01066667777', datetime(2026, 7, 9, 8, 0, 0))
        before_invitations = query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count']
        before_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']

        res = self._list({'search_name': 'Read'})
        self.assertEqual(res.status_code, 200)

        after_invitations = query_db("SELECT COUNT(*) AS count FROM invitations", one=True)['count']
        after_leads = query_db("SELECT COUNT(*) AS count FROM crm_leads", one=True)['count']
        self.assertEqual(before_invitations, after_invitations)
        self.assertEqual(before_leads, after_leads)

    def test_12_response_shape_includes_provenance_fields(self):
        self.login_as('pbi1_bulk', 51001)
        self._invitation(2001, 'Shape Test', '01077778888', datetime(2026, 7, 10, 8, 0, 0), used_by='shape_user', inviter_member_id=70001, inviter_name='PBI1 Inviter')

        res = self._list()
        self.assertEqual(res.status_code, 200)
        item = res.get_json()['items'][0]
        self.assertEqual(item['candidate_key'], '01077778888')
        self.assertEqual(item['invitation_id'], 2001)
        self.assertEqual(item['name'], 'Shape Test')
        self.assertEqual(item['phone'], '01077778888')
        self.assertEqual(item['used_by'], 'shape_user')
        self.assertEqual(item['inviter_member_id'], 70001)
        self.assertEqual(item['inviter_name'], 'PBI1 Inviter')


if __name__ == '__main__':
    unittest.main()
