import unittest
from datetime import timedelta
from unittest.mock import patch

from system_app.app import app
from system_app.func import get_cairo_now
from system_app import queries


class TestOfflineAttendanceEndpoints(unittest.TestCase):
    def setUp(self):
        self.old_testing = app.config.get('TESTING')
        self.old_csrf = app.config.get('WTF_CSRF_ENABLED')
        app.config['TESTING'] = True
        app.config['WTF_CSRF_ENABLED'] = False
        self.client = app.test_client()

    def tearDown(self):
        app.config['TESTING'] = self.old_testing
        app.config['WTF_CSRF_ENABLED'] = self.old_csrf

    def user(self):
        return {
            'id': 123,
            'username': 'attendance_agent',
            'email': 'agent@example.test',
            'is_approved': True,
            'permissions': {'attendance': True},
        }

    def authenticate(self):
        with self.client.session_transaction() as stored_session:
            stored_session['user_id'] = 123
            stored_session['username'] = 'attendance_agent'

    def operation(self, member_id=42):
        captured = get_cairo_now()
        return {
            'client_operation_id': '4e6f0ca8-3f74-4fd4-9c1e-3a89e6e1f8f8',
            'member_id': member_id,
            'member_name': 'untrusted client name',
            'attendance_date': captured.strftime('%Y-%m-%d'),
            'captured_at_device': captured.isoformat(),
        }

    def test_snapshot_requires_authentication(self):
        response = self.client.get('/api/attendance/offline-snapshot')
        self.assertEqual(response.status_code, 302)

    def test_snapshot_contains_only_allowed_fields(self):
        self.authenticate()
        with patch('system_app.app.query_db', side_effect=[self.user(), [{
            'member_id': 42, 'name': 'A Member', 'membership_status': 'VAL', 'end_date': '2099-01-01',
            'email': 'must-not-leak@example.test',
        }]]):
            response = self.client.get('/api/attendance/offline-snapshot')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            set(response.json['members'][0]),
            {'member_id', 'name', 'membership_status', 'end_date'},
        )
        self.assertEqual(response.headers['Cache-Control'], 'no-store, private')

    def test_valid_operation_is_sent_to_transactional_processor(self):
        self.authenticate()
        operation = self.operation()
        with patch('system_app.app.query_db', return_value=self.user()), patch(
            'system_app.app.process_offline_attendance_operations',
            return_value=[{'client_operation_id': operation['client_operation_id'], 'result_code': 'synced'}],
        ) as processor:
            response = self.client.post('/api/attendance/offline-sync', json={'operations': [operation]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['results'][0]['result_code'], 'synced')
        processor.assert_called_once()
        self.assertEqual(processor.call_args.args[0][0]['member_id'], 42)
        self.assertNotIn('member_name', processor.call_args.args[0][0])

    def test_invalid_payload_and_batch_limit_are_rejected(self):
        self.authenticate()
        with patch('system_app.app.query_db', return_value=self.user()):
            invalid = self.client.post('/api/attendance/offline-sync', json={'operations': [{
                **self.operation(), 'client_operation_id': 'not-a-uuid',
            }]})
            too_large = self.client.post('/api/attendance/offline-sync', json={
                'operations': [self.operation(member_id=i) for i in range(51)],
            })
        self.assertEqual(invalid.status_code, 200)
        self.assertEqual(invalid.json['results'][0]['result_code'], 'validation_error')
        self.assertEqual(too_large.status_code, 413)

    def test_stale_or_mismatched_capture_date_is_validation_error(self):
        self.authenticate()
        operation = self.operation()
        operation['attendance_date'] = (get_cairo_now() - timedelta(days=1)).strftime('%Y-%m-%d')
        with patch('system_app.app.query_db', return_value=self.user()), patch(
            'system_app.app.process_offline_attendance_operations'
        ) as processor:
            response = self.client.post('/api/attendance/offline-sync', json={'operations': [operation]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['results'][0]['result_code'], 'validation_error')
        processor.assert_not_called()

    def test_temporary_sync_failure_preserves_authenticated_session(self):
        self.authenticate()
        with patch('system_app.app.query_db', return_value=self.user()), patch(
            'system_app.app.process_offline_attendance_operations',
            side_effect=queries.OperationalError('temporary failure'),
        ):
            response = self.client.post('/api/attendance/offline-sync', json={
                'operations': [self.operation()],
            })
        self.assertEqual(response.status_code, 503)
        with self.client.session_transaction() as stored_session:
            self.assertEqual(stored_session['user_id'], 123)
            self.assertEqual(stored_session['username'], 'attendance_agent')

    def test_missing_idempotency_table_is_feature_unavailable(self):
        self.authenticate()
        with patch('system_app.app.query_db', return_value=self.user()), patch(
            'system_app.app.process_offline_attendance_operations',
            side_effect=queries.psycopg2.errors.UndefinedTable('missing table'),
        ):
            response = self.client.post('/api/attendance/offline-sync', json={
                'operations': [self.operation()],
            })
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error'], 'offline_feature_unavailable')
        self.assertNotIn('relation', response.get_data(as_text=True))

    def test_service_worker_and_template_are_attendance_scoped(self):
        with open('system_app/static/sw.js', encoding='utf-8') as service_worker:
            source = service_worker.read()
        with open('system_app/static/js/attendance_offline.js', encoding='utf-8') as script:
            js = script.read()
        self.assertIn('rival-attendance-shell-v1', source)
        self.assertIn("request.method !== 'GET'", source)
        self.assertIn("url.pathname === '/attendance_table'", source)
        self.assertIn("method: 'POST'", js)
        self.assertIn("cache: 'no-store'", js)
        self.assertIn('indexedDB.open', js)
        self.assertIn('cursor.value.scope === scope', js)
        self.assertIn('attendance-logout-form', open('system_app/templates/attendance_table.html', encoding='utf-8').read())
        self.assertIn("url.pathname === '/attendance_table'", source)
        self.assertNotIn('offline-snapshot', source)
        self.assertNotIn('offline-sync', source)
        self.assertNotIn('password', js.lower())
        self.assertNotIn('session cookies', js.lower())


if __name__ == '__main__':
    unittest.main()
