import unittest
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from system_app.app import app
from system_app import queries
from system_app.func import get_cairo_now


class TestAttendanceOfflinePhase1(unittest.TestCase):
    def setUp(self):
        self.old_enabled = app.config['ATTENDANCE_OFFLINE_ENABLED']
        self.old_csrf = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        self.user = {
            'id': 42, 'username': 'attendance-agent', 'is_approved': True,
            'permissions': {'attendance': True},
        }

    def tearDown(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = self.old_enabled
        app.config['WTF_CSRF_ENABLED'] = self.old_csrf

    def authenticate(self):
        with self.client.session_transaction() as session:
            session['user_id'] = self.user['id']

    def operation(self):
        captured = get_cairo_now()
        return {
            'client_operation_id': str(uuid4()), 'member_id': 7,
            'attendance_date': captured.date().isoformat(), 'captured_at_device': captured.isoformat(),
        }

    def test_disabled_endpoints_are_json_and_do_not_require_database(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = False
        for method in ('get', 'post'):
            response = getattr(self.client, method)(
                '/api/attendance/offline-snapshot' if method == 'get' else '/api/attendance/offline-sync',
                json={'operations': []} if method == 'post' else None,
            )
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.json['error'], 'offline_feature_disabled')
            self.assertIn('no-store', response.headers['Cache-Control'])

    def test_snapshot_is_authenticated_sanitized_and_scoped(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.query_db', side_effect=[[
                {'num': 1, 'member_id': 7, 'name': 'A', 'end_date': '2099-01-01',
                 'membership_status': 'VAL', 'attendance_time': '10:00:00',
                 'attendance_date': '2026-09-15', 'day': 'Tuesday', 'comment': None,
                 'email': 'must-not-leak'},
            ], [{'member_id': 7, 'name': 'A', 'membership_status': 'VAL',
                 'end_date': '2099-01-01', 'phone': 'must-not-leak'}]],
        ):
            response = self.client.get('/api/attendance/offline-snapshot')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['scope'])
        self.assertEqual(set(response.json['members'][0]), {
            'member_id', 'name', 'membership_status', 'end_date',
        })
        self.assertEqual(set(response.json['attendance_rows'][0]), {
            'num', 'member_id', 'name', 'end_date', 'membership_status',
            'attendance_time', 'attendance_date', 'day', 'comment',
        })
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')

    def test_sync_is_csrf_protected_and_uses_authenticated_user(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        operation = self.operation()
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.process_offline_attendance_operations',
            return_value=[{'client_operation_id': operation['client_operation_id'], 'result_code': 'synced'}],
        ) as processor, patch('system_app.app.csrf.protect'):
            response = self.client.post(
                '/api/attendance/offline-sync', json={'operations': [operation]},
            )
        self.assertEqual(response.status_code, 200)
        processor.assert_called_once_with([{
            'client_operation_id': operation['client_operation_id'],
            'member_id': 7,
            'server_business_date': datetime.fromisoformat(operation['captured_at_device']).date(),
            'attendance_at': datetime.fromisoformat(operation['captured_at_device']),
        }], 42, 'attendance-agent')

    def test_missing_csrf_is_json_403(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        app.config['WTF_CSRF_ENABLED'] = True
        with patch('system_app.app.get_current_user', return_value=self.user):
            response = self.client.post(
                '/api/attendance/offline-sync', json={'operations': [self.operation()]},
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json['error'], 'csrf_failure')

    def test_shared_writer_returns_typed_results(self):
        self.assertTrue(hasattr(queries, 'record_attendance_transaction'))
        self.assertTrue(hasattr(queries, 'process_offline_attendance_operations'))

    def test_attendance_page_has_no_offline_markup_when_disabled(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = False
        self.authenticate()
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.query_db', return_value=[],
        ):
            response = self.client.get('/attendance_table')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn('attendance_offline.js', html)
        self.assertNotIn('Offline Mode', html)

    def test_attendance_page_loads_enhancement_only_when_enabled(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.query_db', return_value=[],
        ):
            response = self.client.get('/attendance_table')
        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn('attendance_offline.js', html)
        self.assertIn('Offline Mode', html)

    def test_scope_is_stable_per_user_but_differs_between_users(self):
        from system_app.app import _attendance_offline_scope
        with app.test_request_context('/'):
            first = _attendance_offline_scope(42)
            same = _attendance_offline_scope(42)
            other = _attendance_offline_scope(43)
        self.assertEqual(first, same)
        self.assertNotEqual(first, other)
        self.assertNotIn('42', first)


class WriterCursor:
    def __init__(self, duplicate=False, failure=None):
        self.queries = []
        self.duplicate = duplicate
        self.failure = failure

    def execute(self, query, args=()):
        if self.failure:
            raise self.failure
        self.queries.append((query, args))

    def fetchone(self):
        query = self.queries[-1][0]
        if 'FROM members' in query:
            return {'id': 7, 'name': 'Member', 'end_date': '2099-01-01', 'membership_status': 'VAL'}
        if 'FROM attendance' in query:
            return {'exists': 1} if self.duplicate else None
        if 'RETURNING num' in query:
            return {'num': 99, 'attendance_time': '23:30:00', 'attendance_date': '2026-09-15', 'day': 'Tuesday'}
        return None

    def close(self):
        pass


class WriterConnection:
    def __init__(self, cursor):
        self.cursor_value = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


class WriterPool:
    def __init__(self, connection):
        self.connection = connection
        self.returned = []

    def getconn(self):
        return self.connection

    def putconn(self, connection, close=False):
        self.returned.append((connection, close))


class TestAttendanceWriterDates(unittest.TestCase):
    def setUp(self):
        self.old_enabled = app.config['ATTENDANCE_OFFLINE_ENABLED']
        self.old_csrf = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()
        self.user = {
            'id': 42, 'username': 'attendance-agent', 'is_approved': True,
            'permissions': {'attendance': True},
        }

    def tearDown(self):
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = self.old_enabled
        app.config['WTF_CSRF_ENABLED'] = self.old_csrf

    def authenticate(self):
        with self.client.session_transaction() as session:
            session['user_id'] = self.user['id']

    def run_writer(self, captured, business_date, duplicate=False):
        cursor = WriterCursor(duplicate=duplicate)
        connection = WriterConnection(cursor)
        with patch.object(queries, 'get_connection_pool', return_value=None), patch.object(
            queries.psycopg2, 'connect', return_value=connection,
        ):
            result = queries.record_attendance_transaction(
                7, business_date=business_date, attendance_at=captured,
            )
        return result, cursor

    def test_same_day_uses_authoritative_date_time_and_day(self):
        import pytz
        cairo = pytz.timezone('Africa/Cairo')
        captured = cairo.localize(datetime(2026, 9, 15, 23, 30, 0))
        result, cursor = self.run_writer(captured, date(2026, 9, 15))
        insert = next(args for query, args in cursor.queries if 'INSERT INTO attendance' in query)
        lock = next(args for query, args in cursor.queries if 'pg_advisory_xact_lock' in query)
        self.assertEqual(result['result_code'], 'synced')
        self.assertEqual(lock[1], '2026-09-15')
        self.assertEqual(insert[-3:], ('23:30:00', '2026-09-15', 'Tuesday'))

    def test_capture_before_midnight_stays_on_captured_date_after_sync(self):
        import pytz
        cairo = pytz.timezone('Africa/Cairo')
        captured = cairo.localize(datetime(2026, 9, 15, 23, 59, 59))
        result, cursor = self.run_writer(captured, date(2026, 9, 15))
        insert = next(args for query, args in cursor.queries if 'INSERT INTO attendance' in query)
        self.assertEqual(result['result_code'], 'synced')
        self.assertEqual(insert[-3:], ('23:59:59', '2026-09-15', 'Tuesday'))

    def test_timezone_conversion_and_duplicate_query_use_cairo_date(self):
        from zoneinfo import ZoneInfo
        captured = datetime(2026, 11, 1, 23, 30, tzinfo=ZoneInfo('America/New_York'))
        cairo_date = captured.astimezone(ZoneInfo('Africa/Cairo')).date()
        result, cursor = self.run_writer(captured, cairo_date, duplicate=True)
        duplicate_query = next(args for query, args in cursor.queries if 'FROM attendance' in query)
        self.assertEqual(result['result_code'], 'duplicate_attendance')
        self.assertEqual(duplicate_query[1], cairo_date.isoformat())

    def test_mismatched_authoritative_date_is_rejected_before_database_access(self):
        import pytz
        captured = pytz.timezone('Africa/Cairo').localize(datetime(2026, 9, 15, 23, 30))
        with self.assertRaises(ValueError):
            queries.record_attendance_transaction(7, business_date=date(2026, 9, 16), attendance_at=captured)

    def test_healthy_pooled_connection_is_returned_for_reuse(self):
        cursor = WriterCursor()
        connection = WriterConnection(cursor)
        connection_pool = WriterPool(connection)
        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            result = queries.record_attendance_transaction(
                7, business_date=date(2026, 9, 15),
                attendance_at=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
            )
        self.assertEqual(result['result_code'], 'synced')
        self.assertEqual(connection_pool.returned, [(connection, False)])

    def test_broken_pooled_connection_is_discarded_and_exception_preserved(self):
        error = queries.OperationalError('connection failed')
        cursor = WriterCursor(failure=error)
        connection = WriterConnection(cursor)
        connection_pool = WriterPool(connection)
        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            with self.assertRaises(queries.OperationalError):
                queries.record_attendance_transaction(
                    7, business_date=date(2026, 9, 15),
                    attendance_at=datetime(2026, 9, 15, 12, 0, tzinfo=timezone.utc),
                )
        self.assertEqual(connection_pool.returned, [(connection, True)])

    def test_old_but_allowed_operation_is_accepted_by_server_validation(self):
        import pytz
        cairo = pytz.timezone('Africa/Cairo')
        server_now = cairo.localize(datetime(2026, 9, 15, 12, 0))
        captured = cairo.localize(datetime(2026, 9, 13, 12, 0))
        operation = {
            'client_operation_id': str(uuid4()), 'member_id': 7,
            'attendance_date': '2026-09-13', 'captured_at_device': captured.isoformat(),
        }
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.get_cairo_now', return_value=server_now,
        ), patch('system_app.app.get_cairo_date', return_value=server_now.date()), patch(
            'system_app.app.process_offline_attendance_operations', return_value=[],
        ) as processor, patch('system_app.app.csrf.protect'):
            response = self.client.post('/api/attendance/offline-sync', json={'operations': [operation]})
        self.assertEqual(response.status_code, 200)
        processor.assert_called_once()

    def test_too_old_and_too_future_operations_are_rejected(self):
        import pytz
        cairo = pytz.timezone('Africa/Cairo')
        server_now = cairo.localize(datetime(2026, 9, 15, 12, 0))
        app.config['ATTENDANCE_OFFLINE_ENABLED'] = True
        self.authenticate()
        operations = []
        for delta in (-3, 2):
            captured = server_now + timedelta(days=delta)
            operations.append({
                'client_operation_id': str(uuid4()), 'member_id': 7,
                'attendance_date': captured.date().isoformat(),
                'captured_at_device': captured.isoformat(),
            })
        with patch('system_app.app.get_current_user', return_value=self.user), patch(
            'system_app.app.get_cairo_now', return_value=server_now,
        ), patch('system_app.app.get_cairo_date', return_value=server_now.date()), patch(
            'system_app.app.process_offline_attendance_operations', return_value=[],
        ) as processor, patch('system_app.app.csrf.protect'):
            response = self.client.post('/api/attendance/offline-sync', json={'operations': operations})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item['result_code'] for item in response.json['results']], ['validation_error', 'validation_error'])
        processor.assert_not_called()


if __name__ == '__main__':
    unittest.main()
