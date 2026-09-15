import unittest
from datetime import datetime
from contextlib import ExitStack
from unittest.mock import Mock, patch

import psycopg2

from system_app.app import app, csrf
from system_app.crm import queries as crm_queries
from system_app.private_training import routes
from system_app.private_training.services import (
    PrivateTrainingForbiddenError,
    PrivateTrainingPendingSessionConflictError,
    PrivateTrainingValidationError,
)


class TestPrivateTrainingCheckinAjax(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        self.user = {
            'id': 12, 'username': 'trainer_one', 'is_approved': True,
            'permissions': {'private_training_trainer': True},
        }
        self.subscription = {
            'id': 21, 'total_sessions': 37, 'approved_count': 1,
            'remaining_sessions': 36, 'pending_count': 1,
            'effective_status': 'ACTIVE',
        }
        self.session_row = {
            'id': 25, 'trainer_display_name': 'Trainer One',
            'checked_in_at': datetime(2026, 9, 15, 18, 19, 7),
            'workout_name': 'Leg Day', 'status': 'PENDING_MEMBER_APPROVAL',
            'approved_at': None,
        }
        with self.client.session_transaction() as session:
            session['user_id'] = self.user['id']

    def _headers(self):
        return {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}

    def _patch_route(self, service_result=None):
        stack = ExitStack()
        stack.enter_context(patch.multiple(
            routes,
            get_current_user=Mock(return_value=self.user),
            create_private_training_session_checkin=Mock(return_value=service_result or self.session_row),
            get_private_training_subscription=Mock(return_value=self.subscription),
            list_private_training_sessions=Mock(return_value=[self.session_row]),
        ))
        stack.enter_context(patch.object(csrf, 'protect'))
        stack.enter_context(patch('system_app.crm.permissions.get_current_user', return_value=self.user))
        return stack

    def test_html_post_preserves_redirect_flash_behavior(self):
        with self._patch_route():
            response = self.client.post(
                '/private-training/subscriptions/21/check-in',
                data={'workout_name': 'Leg Day', 'csrf_token': 'valid'},
            )
        self.assertEqual(response.status_code, 302)
        self.assertIn('/private-training/subscriptions/21', response.location)

    def test_ajax_success_returns_authoritative_values_and_history(self):
        with self._patch_route():
            response = self.client.post(
                '/private-training/subscriptions/21/check-in',
                data={'workout_name': 'Leg Day', 'csrf_token': 'valid'},
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json['subscription']['remaining_sessions'], 36)
        self.assertEqual(response.json['subscription']['pending_sessions'], 1)
        self.assertEqual(response.json['session']['id'], 25)
        self.assertEqual(response.json['session']['workout_name'], 'Leg Day')
        self.assertEqual(response.json['sessions'][0]['id'], 25)

    def test_ajax_validation_and_business_errors_are_safe_json(self):
        for exception, code, status in (
            (PrivateTrainingValidationError('bad'), 'validation_error', 400),
            (PrivateTrainingPendingSessionConflictError('pending'), 'pending_session_exists', 409),
            (PrivateTrainingForbiddenError('no'), 'forbidden', 403),
        ):
            with self.subTest(code=code), self._patch_route():
                routes.create_private_training_session_checkin.side_effect = exception
                response = self.client.post(
                    '/private-training/subscriptions/21/check-in',
                    data={'workout_name': 'Leg Day', 'csrf_token': 'valid'},
                    headers=self._headers(),
                )
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json, {'ok': False, 'error': code, 'message': response.json['message']})
            self.assertNotIn('traceback', response.get_data(as_text=True).lower())

    def test_ajax_database_failure_is_retry_ambiguous_not_success(self):
        with self._patch_route():
            routes.create_private_training_session_checkin.side_effect = psycopg2.OperationalError('secret db detail')
            response = self.client.post(
                '/private-training/subscriptions/21/check-in',
                data={'workout_name': 'Leg Day', 'csrf_token': 'valid'},
                headers=self._headers(),
            )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error'], 'temporary_database_error')
        self.assertNotIn('secret db detail', response.get_data(as_text=True))

    def test_ajax_missing_csrf_is_safe_json(self):
        with patch.object(routes, 'get_current_user', return_value=self.user), patch(
            'system_app.crm.permissions.get_current_user', return_value=self.user
        ):
            response = self.client.post(
                '/private-training/subscriptions/21/check-in',
                data={'workout_name': 'Leg Day'}, headers=self._headers(),
            )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json['error'], 'csrf_failure')

    def test_html_missing_csrf_keeps_existing_response_behavior(self):
        response = self.client.post(
            '/private-training/subscriptions/21/check-in',
            data={'workout_name': 'Leg Day'},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('CSRF token missing or invalid', response.get_data(as_text=True))

    def test_unauthenticated_ajax_is_not_reported_as_success(self):
        client = app.test_client()
        response = client.post(
            '/private-training/subscriptions/21/check-in',
            data={'workout_name': 'Leg Day'}, headers=self._headers(),
        )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json['error'], 'unauthorized')


class FakeCursor:
    def __init__(self, error=None):
        self.error = error

    def close(self):
        pass


class FakeConnection:
    def __init__(self, cursor=None, rollback_error=None):
        self.cursor_value = cursor or FakeCursor()
        self.rollback_error = rollback_error
        self.commits = 0
        self.rollbacks = 0
        self.closes = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_value

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1
        if self.rollback_error:
            raise self.rollback_error

    def close(self):
        self.closes += 1


class FakePool:
    def __init__(self, connection):
        self.connection = connection
        self.calls = []

    def getconn(self):
        return self.connection

    def putconn(self, connection, close=False):
        self.calls.append((connection, close))


class TestPrivateTrainingTransactionPool(unittest.TestCase):
    def run_transaction(self, pool, callback):
        from system_app import queries as app_queries
        with patch.object(app_queries, 'get_connection_pool', return_value=pool), patch.object(
            app_queries, 'get_database_url', return_value='postgresql://local-test-only'
        ):
            return crm_queries.run_in_transaction(callback)

    def test_healthy_pooled_connection_returned_once(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        self.assertEqual(self.run_transaction(pool, lambda cur: 'ok'), 'ok')
        self.assertEqual(pool.calls, [(connection, False)])
        self.assertEqual(connection.closes, 0)

    def test_operational_error_pooled_connection_discarded_once(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        error = psycopg2.OperationalError('broken')
        with self.assertRaises(psycopg2.OperationalError):
            self.run_transaction(pool, lambda cur: (_ for _ in ()).throw(error))
        self.assertEqual(pool.calls, [(connection, True)])

    def test_interface_error_pooled_connection_discarded_once(self):
        connection = FakeConnection()
        pool = FakePool(connection)
        error = psycopg2.InterfaceError('broken')
        with self.assertRaises(psycopg2.InterfaceError):
            self.run_transaction(pool, lambda cur: (_ for _ in ()).throw(error))
        self.assertEqual(pool.calls, [(connection, True)])

    def test_direct_connection_is_closed_once(self):
        connection = FakeConnection()
        from system_app import queries as app_queries
        with patch.object(app_queries, 'get_connection_pool', return_value=None), patch.object(
            app_queries, 'get_database_url', return_value='postgresql://local-test-only'
        ), patch('psycopg2.connect', return_value=connection):
            self.assertEqual(crm_queries.run_in_transaction(lambda cur: 'ok'), 'ok')
        self.assertEqual(connection.closes, 1)

    def test_rollback_failure_preserves_original_exception(self):
        connection = FakeConnection(rollback_error=RuntimeError('rollback failed'))
        pool = FakePool(connection)
        original = ValueError('business failure')
        with self.assertRaisesRegex(ValueError, 'business failure'):
            self.run_transaction(pool, lambda cur: (_ for _ in ()).throw(original))
        self.assertEqual(pool.calls, [(connection, False)])


if __name__ == '__main__':
    unittest.main()
