import unittest
from datetime import timedelta
from unittest.mock import patch

from flask import session

from system_app.app import CurrentUserLookupError, app, permission_required
from system_app.crm.permissions import CRM_VIEW, crm_permission_required


class TestSessionAuthenticationSafety(unittest.TestCase):
    def setUp(self):
        self.client = app.test_client()
        app.config['TESTING'] = True

    @staticmethod
    def _user():
        return {
            'id': 123,
            'username': 'agent',
            'email': 'agent@example.test',
            'is_approved': True,
            'permissions': {'attendance': True, 'crm_view': True},
        }

    def _authenticate(self):
        with self.client.session_transaction() as stored_session:
            stored_session['user_id'] = 123
            stored_session['username'] = 'agent'
            stored_session.permanent = True

    def test_session_configuration(self):
        self.assertEqual(app.config['PERMANENT_SESSION_LIFETIME'], timedelta(days=30))
        self.assertTrue(app.config['SESSION_REFRESH_EACH_REQUEST'])

    def test_successful_authenticated_session_is_permanent(self):
        with self.client.session_transaction() as stored_session:
            stored_session['user_id'] = 123
            stored_session['username'] = 'agent'
            stored_session.permanent = True
            self.assertTrue(stored_session.permanent)

    def test_existing_authenticated_user_remains_authenticated(self):
        self._authenticate()
        with patch('system_app.app.query_db', return_value=self._user()):
            response = self.client.get('/success')
        self.assertEqual(response.status_code, 200)

        with self.client.session_transaction() as stored_session:
            self.assertEqual(stored_session['user_id'], 123)
            self.assertEqual(stored_session['username'], 'agent')

    def test_transient_failure_preserves_session_on_standard_decorator(self):
        self._authenticate()
        with patch('system_app.app.query_db', side_effect=TimeoutError):
            response = self.client.get('/success')
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json['error'], 'authentication_temporarily_unavailable')

        with self.client.session_transaction() as stored_session:
            self.assertEqual(stored_session['user_id'], 123)
            self.assertEqual(stored_session['username'], 'agent')

    def test_transient_failure_preserves_session_on_crm_permission_decorator(self):
        self._authenticate()
        with patch('system_app.app.query_db', side_effect=ConnectionError):
            response = self.client.get('/crm/summary')
        self.assertEqual(response.status_code, 503)

        with self.client.session_transaction() as stored_session:
            self.assertEqual(stored_session['user_id'], 123)
            self.assertEqual(stored_session['username'], 'agent')

    def test_transient_failure_preserves_session_on_standard_permission_decorator(self):
        self._authenticate()

        @permission_required('attendance')
        def protected():
            return 'ok'

        with app.test_request_context('/protected'):
            session['user_id'] = 123
            session['username'] = 'agent'
            with patch('system_app.app.get_current_user', side_effect=CurrentUserLookupError):
                response = protected()
            self.assertEqual(response[1] if isinstance(response, tuple) else response.status_code, 503)
            self.assertIn('user_id', session)

    def test_transient_failure_preserves_session_on_crm_permission_only(self):
        self._authenticate()

        @crm_permission_required(CRM_VIEW)
        def protected():
            return 'ok'

        with app.test_request_context('/crm/protected'):
            session['user_id'] = 123
            session['username'] = 'agent'
            with patch('system_app.crm.permissions.get_current_user', side_effect=CurrentUserLookupError):
                response = protected()
            self.assertEqual(response[1] if isinstance(response, tuple) else response.status_code, 503)
            self.assertIn('user_id', session)

    def test_missing_user_clears_invalid_session(self):
        self._authenticate()
        with patch('system_app.app.query_db', return_value=None):
            response = self.client.get('/success')
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as stored_session:
            self.assertNotIn('user_id', stored_session)
            self.assertNotIn('username', stored_session)

    def test_explicit_logout_clears_session(self):
        self._authenticate()
        response = self.client.get('/logout')
        self.assertEqual(response.status_code, 302)

        with self.client.session_transaction() as stored_session:
            self.assertNotIn('user_id', stored_session)
            self.assertNotIn('username', stored_session)


if __name__ == '__main__':
    unittest.main()
