"""
test_expiring_memberships.py

Regression tests for the Expiring Memberships Alert feature.

Coverage:
  - Dashboard count bucket boundary semantics (9 date boundaries)
  - filtered_members?expires_within= route (7, 14, 30)
  - Bucket disjointness
  - Invalid expires_within safety
  - NULL / empty / malformed end_date excluded
  - Dashboard card <a href> attributes and labels
  - Pagination URL preserves expires_within
  - Unauthenticated access blocked
"""

import unittest
from datetime import timedelta
from system_app.app import app
from system_app.queries import query_db
from system_app.func import get_cairo_date


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today():
    return get_cairo_date()


def _date_str(delta_days):
    return (_today() + timedelta(days=delta_days)).strftime('%Y-%m-%d')


def _create_member(end_date, member_id):
    query_db(
        """
        INSERT INTO members (id, name, phone, end_date, membership_packages,
                             membership_fees, membership_status)
        VALUES (%s, %s, %s, %s, '1 Month', 500.0, 'VAL')
        ON CONFLICT (id) DO UPDATE SET end_date = EXCLUDED.end_date
        """,
        (member_id, 'TestExpiry%d' % member_id, '90%06d' % member_id, end_date),
        commit=True,
    )


def _delete_members(ids):
    for mid in ids:
        query_db("DELETE FROM members WHERE id = %s", (mid,), commit=True)


# ---------------------------------------------------------------------------
# Base test class
# ---------------------------------------------------------------------------

class ExpiryTestBase(unittest.TestCase):

    def setUp(self):
        self.app = app
        self.app.config['TESTING'] = True
        self.app.config['WTF_CSRF_ENABLED'] = False
        self.client = self.app.test_client()
        self._test_ids = []

        query_db(
            """
            INSERT INTO users (id, username, email, password, is_approved, permissions)
            VALUES (89001, 'expiry_test_user', 'expiry@test.com', 'pwd', TRUE,
                    '{"super_admin": true}')
            ON CONFLICT (id) DO NOTHING
            """,
            commit=True,
        )
        with self.client.session_transaction() as sess:
            sess['user_id'] = 89001
            sess['username'] = 'expiry_test_user'

    def tearDown(self):
        _delete_members(self._test_ids)
        query_db("DELETE FROM users WHERE id = 89001", commit=True)

    def _add(self, member_id, end_date):
        _create_member(end_date, member_id)
        self._test_ids.append(member_id)

    def _json(self, expires_within):
        resp = self.client.get(
            '/filtered_members?expires_within=%s&format=json' % expires_within,
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )
        self.assertEqual(resp.status_code, 200)
        return resp.get_json()

    def _ids_in_bucket(self, expires_within):
        return {m['id'] for m in self._json(expires_within).get('members', [])}


# ---------------------------------------------------------------------------
# A. Bucket boundary semantics
# ---------------------------------------------------------------------------

class TestBucketBoundaries(ExpiryTestBase):

    def test_A01_today_in_urgent(self):
        """end_date == today -> Urgent."""
        self._add(89101, _date_str(0))
        self.assertIn(89101, self._ids_in_bucket(7))

    def test_A02_today_plus_1_in_urgent(self):
        self._add(89102, _date_str(1))
        self.assertIn(89102, self._ids_in_bucket(7))

    def test_A03_today_plus_7_in_urgent(self):
        """end_date == today+7 -> Urgent (inclusive upper bound)."""
        self._add(89103, _date_str(7))
        self.assertIn(89103, self._ids_in_bucket(7))

    def test_A04_today_plus_7_not_in_warning(self):
        """end_date == today+7 -> NOT Warning (disjoint)."""
        self._add(89103, _date_str(7))
        self.assertNotIn(89103, self._ids_in_bucket(14))

    def test_A05_today_plus_8_in_warning(self):
        self._add(89104, _date_str(8))
        self.assertIn(89104, self._ids_in_bucket(14))

    def test_A06_today_plus_8_not_in_urgent(self):
        self._add(89104, _date_str(8))
        self.assertNotIn(89104, self._ids_in_bucket(7))

    def test_A07_today_plus_14_in_warning(self):
        """end_date == today+14 -> Warning (inclusive)."""
        self._add(89105, _date_str(14))
        self.assertIn(89105, self._ids_in_bucket(14))

    def test_A08_today_plus_14_not_in_upcoming(self):
        self._add(89105, _date_str(14))
        self.assertNotIn(89105, self._ids_in_bucket(30))

    def test_A09_today_plus_15_in_upcoming(self):
        self._add(89106, _date_str(15))
        self.assertIn(89106, self._ids_in_bucket(30))

    def test_A10_today_plus_15_not_in_warning(self):
        self._add(89106, _date_str(15))
        self.assertNotIn(89106, self._ids_in_bucket(14))

    def test_A11_today_plus_30_in_upcoming(self):
        """end_date == today+30 -> Upcoming (inclusive upper bound)."""
        self._add(89107, _date_str(30))
        self.assertIn(89107, self._ids_in_bucket(30))

    def test_A12_today_plus_31_in_no_bucket(self):
        """end_date == today+31 -> no bucket."""
        self._add(89108, _date_str(31))
        for ew in [7, 14, 30]:
            self.assertNotIn(89108, self._ids_in_bucket(ew),
                             'today+31 must not appear in bucket %d' % ew)

    def test_A13_yesterday_in_no_bucket(self):
        """end_date == today-1 -> already expired, no bucket."""
        self._add(89109, _date_str(-1))
        for ew in [7, 14, 30]:
            self.assertNotIn(89109, self._ids_in_bucket(ew))


# ---------------------------------------------------------------------------
# B. Disjointness
# ---------------------------------------------------------------------------

class TestDisjointness(ExpiryTestBase):

    def test_B01_member_in_exactly_one_bucket(self):
        """A member must appear in exactly one bucket."""
        self._add(89110, _date_str(3))  # urgent
        in_7  = 89110 in self._ids_in_bucket(7)
        in_14 = 89110 in self._ids_in_bucket(14)
        in_30 = 89110 in self._ids_in_bucket(30)
        self.assertTrue(in_7,  "today+3 must be in urgent")
        self.assertFalse(in_14, "today+3 must NOT be in warning")
        self.assertFalse(in_30, "today+3 must NOT be in upcoming")

    def test_B02_three_members_one_per_bucket(self):
        """One member per bucket, each appears in exactly its bucket."""
        self._add(89111, _date_str(3))   # urgent
        self._add(89112, _date_str(10))  # warning
        self._add(89113, _date_str(20))  # upcoming

        urgent_ids   = self._ids_in_bucket(7)
        warning_ids  = self._ids_in_bucket(14)
        upcoming_ids = self._ids_in_bucket(30)

        self.assertIn(89111, urgent_ids)
        self.assertNotIn(89111, warning_ids)
        self.assertNotIn(89111, upcoming_ids)

        self.assertNotIn(89112, urgent_ids)
        self.assertIn(89112, warning_ids)
        self.assertNotIn(89112, upcoming_ids)

        self.assertNotIn(89113, urgent_ids)
        self.assertNotIn(89113, warning_ids)
        self.assertIn(89113, upcoming_ids)


# ---------------------------------------------------------------------------
# C. Invalid expires_within
# ---------------------------------------------------------------------------

class TestInvalidExpiresWithin(ExpiryTestBase):

    def test_C01_does_not_crash(self):
        for bad in ['0', '13', '31', 'abc', '', 'null', '99']:
            resp = self.client.get('/filtered_members?expires_within=%s' % bad)
            self.assertEqual(resp.status_code, 200,
                             'Unexpected error for expires_within=%r' % bad)

    def test_C02_invalid_returns_same_as_no_filter(self):
        resp_base = self.client.get(
            '/filtered_members?format=json',
            headers={'X-Requested-With': 'XMLHttpRequest'})
        resp_bad  = self.client.get(
            '/filtered_members?expires_within=999&format=json',
            headers={'X-Requested-With': 'XMLHttpRequest'})
        base_count = resp_base.get_json().get('total_count', -1)
        bad_count  = resp_bad.get_json().get('total_count', -2)
        self.assertEqual(base_count, bad_count)


# ---------------------------------------------------------------------------
# D. NULL / empty / malformed end_date
# ---------------------------------------------------------------------------

class TestBadEndDates(ExpiryTestBase):

    def test_D01_null_excluded(self):
        self._add(89120, None)
        for ew in [7, 14, 30]:
            self.assertNotIn(89120, self._ids_in_bucket(ew))

    def test_D02_empty_string_excluded(self):
        self._add(89121, '')
        for ew in [7, 14, 30]:
            self.assertNotIn(89121, self._ids_in_bucket(ew))

    def test_D03_malformed_excluded(self):
        self._add(89122, 'not-a-date')
        for ew in [7, 14, 30]:
            self.assertNotIn(89122, self._ids_in_bucket(ew))

    def test_D04_too_short_excluded(self):
        self._add(89123, '2026')
        for ew in [7, 14, 30]:
            self.assertNotIn(89123, self._ids_in_bucket(ew))


# ---------------------------------------------------------------------------
# E. Dashboard card hrefs and labels
# ---------------------------------------------------------------------------

class TestDashboardCards(ExpiryTestBase):

    def _index_html(self):
        # Insert one member per bucket so all 3 cards render
        self._add(89130, _date_str(1))   # urgent
        self._add(89131, _date_str(10))  # warning
        self._add(89132, _date_str(20))  # upcoming
        resp = self.client.get('/')
        self.assertEqual(resp.status_code, 200)
        return resp.data.decode()

    def test_E01_urgent_href_present(self):
        html = self._index_html()
        self.assertIn('expires_within=7', html)

    def test_E02_warning_href_present(self):
        html = self._index_html()
        self.assertIn('expires_within=14', html)

    def test_E03_upcoming_href_present(self):
        html = self._index_html()
        self.assertIn('expires_within=30', html)

    def test_E04_cards_are_anchors_not_divs(self):
        import re
        html = self._index_html()
        # No bare <div class="alert-item ..."> should exist
        bare_div = re.search(r'<div\s[^>]*class="[^"]*alert-item[^"]*"', html)
        self.assertIsNone(bare_div, 'alert-item should be <a>, not <div>')

    def test_E05_urgent_label(self):
        html = self._index_html()
        self.assertIn('Expiring within 7 days', html)

    def test_E06_warning_label(self):
        html = self._index_html()
        self.assertIn('Expiring in 8', html)  # "Expiring in 8–14 days"

    def test_E07_upcoming_label(self):
        html = self._index_html()
        self.assertIn('Expiring in 15', html)  # "Expiring in 15–30 days"


# ---------------------------------------------------------------------------
# F. Pagination / URL state
# ---------------------------------------------------------------------------

class TestPaginationState(ExpiryTestBase):

    def test_F01_expires_within_in_page_js(self):
        """The template JS must reference expires_within for URL preservation."""
        resp = self.client.get('/filtered_members?expires_within=7')
        self.assertEqual(resp.status_code, 200)
        html = resp.data.decode()
        self.assertIn('expires_within', html)

    def test_F02_page_2_with_expires_within_200(self):
        """Paginated URL with expires_within must not crash."""
        resp = self.client.get('/filtered_members?expires_within=7&page=2')
        self.assertEqual(resp.status_code, 200)

    def test_F03_expires_within_with_search_200(self):
        """expires_within combined with search params must not crash."""
        resp = self.client.get(
            '/filtered_members?expires_within=14&search_name=Test')
        self.assertEqual(resp.status_code, 200)


# ---------------------------------------------------------------------------
# G. Authentication
# ---------------------------------------------------------------------------

class TestAuthentication(ExpiryTestBase):

    def test_G01_unauth_dashboard_redirects(self):
        with self.app.test_client() as c:
            resp = c.get('/')
            self.assertIn(resp.status_code, (302, 401))

    def test_G02_unauth_filtered_members_redirects(self):
        with self.app.test_client() as c:
            resp = c.get('/filtered_members?expires_within=7')
            self.assertIn(resp.status_code, (302, 401))


if __name__ == '__main__':
    unittest.main()
