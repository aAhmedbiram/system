import unittest
from unittest.mock import Mock, call, patch

from system_app.app import app
from system_app import queries


class FakeCursor:
    def __init__(self, rows=None, execute_error=None):
        self.rows = rows or []
        self.execute_error = execute_error

    def execute(self, query, args):
        if self.execute_error:
            raise self.execute_error

    def fetchall(self):
        return self.rows

    def close(self):
        pass


class FakeConnection:
    def __init__(self, rows=None, execute_error=None):
        self.cursor_obj = FakeCursor(rows, execute_error)
        self.rollback_calls = 0
        self.close_calls = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def rollback(self):
        self.rollback_calls += 1

    def close(self):
        self.close_calls += 1


class OfflineCursor:
    def __init__(self, fail=False):
        self.fail = fail
        self.last_query = ''
        self.fetchone_calls = 0

    def execute(self, query, args=None):
        self.last_query = query
        if isinstance(self.fail, BaseException):
            raise self.fail

    def fetchone(self):
        self.fetchone_calls += 1
        if 'INSERT INTO offline_attendance_operations' in self.last_query:
            return {'client_operation_id': '4e6f0ca8-3f74-4fd4-9c1e-3a89e6e1f8f8'}
        if 'FROM members' in self.last_query:
            return {'id': 42, 'name': 'Member', 'end_date': '2099-01-01', 'membership_status': 'VAL'}
        if 'FROM attendance' in self.last_query:
            return None
        return None

    def close(self):
        pass


class OfflineConnection:
    def __init__(self, fail=False):
        self.cursor_obj = OfflineCursor(fail=fail)
        self.rollback_calls = 0
        self.close_calls = 0
        self.commit_calls = 0

    def cursor(self, cursor_factory=None):
        return self.cursor_obj

    def rollback(self):
        self.rollback_calls += 1

    def commit(self):
        self.commit_calls += 1

    def close(self):
        self.close_calls += 1


class TestQueryPoolResilience(unittest.TestCase):
    def offline_operation(self):
        return {
            'client_operation_id': '4e6f0ca8-3f74-4fd4-9c1e-3a89e6e1f8f8',
            'member_id': 42,
            'server_business_date': __import__('datetime').date.today(),
            'attendance_time': '10:00:00',
            'attendance_day': 'Monday',
        }

    def test_offline_healthy_pooled_connection_is_returned_normally(self):
        connection = OfflineConnection()
        connection_pool = Mock()
        connection_pool.getconn.return_value = connection
        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            queries.process_offline_attendance_operations([self.offline_operation()], 123, 'agent')
        connection_pool.putconn.assert_called_once_with(connection)
        self.assertEqual(connection.close_calls, 0)

    def test_offline_broken_pooled_connection_is_discarded(self):
        for error_type in (queries.OperationalError, queries.InterfaceError):
            connection = OfflineConnection()
            connection_pool = Mock()
            connection_pool.getconn.return_value = connection
            connection.cursor_obj.fail = error_type('closed')
            with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
                with self.assertRaises(error_type):
                    queries.process_offline_attendance_operations([self.offline_operation()], 123, 'agent')
            connection_pool.putconn.assert_called_once_with(connection, close=True)
            self.assertEqual(connection.close_calls, 0)

    def test_offline_direct_connection_is_closed_directly(self):
        connection = OfflineConnection()
        with patch.object(queries, 'get_connection_pool', return_value=None), \
                patch.object(queries.psycopg2, 'connect', return_value=connection):
            queries.process_offline_attendance_operations([self.offline_operation()], 123, 'agent')
        self.assertEqual(connection.close_calls, 1)

    def test_replay_preserves_each_terminal_result(self):
        for code in ('synced', 'duplicate_attendance', 'invalid_member',
                     'inactive_membership', 'validation_error', 'unauthorized'):
            replay = queries._offline_replay_result('operation-id', {'result_code': code})
            self.assertEqual(replay['result_code'], code)
            self.assertTrue(replay['replayed'])
    def test_healthy_pooled_connection_is_returned_normally(self):
        connection = FakeConnection(rows=[{'id': 1}])
        connection_pool = Mock()
        connection_pool.getconn.return_value = connection

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            self.assertEqual(queries.query_db('SELECT 1'), [{'id': 1}])

        connection_pool.putconn.assert_called_once_with(connection)
        self.assertEqual(connection.close_calls, 0)

    def test_broken_pooled_connection_is_discarded_with_close_true(self):
        connection = FakeConnection(execute_error=queries.OperationalError('closed'))
        connection_pool = Mock()
        connection_pool.getconn.return_value = connection

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            with self.assertRaises(queries.OperationalError):
                queries.query_db('UPDATE users SET username = %s', ('x',))

        connection_pool.putconn.assert_called_once_with(connection, close=True)
        self.assertEqual(connection.close_calls, 0)

    def test_broken_connection_is_never_returned_normally_afterward(self):
        broken = FakeConnection(execute_error=queries.InterfaceError('closed'))
        healthy = FakeConnection(rows=[{'id': 2}])
        connection_pool = Mock()
        connection_pool.getconn.side_effect = [broken, healthy]

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            self.assertEqual(queries.query_db('SELECT 1'), [{'id': 2}])

        self.assertEqual(
            connection_pool.putconn.call_args_list,
            [call(broken, close=True), call(healthy)],
        )

    def test_select_gets_one_retry_using_a_fresh_connection(self):
        first = FakeConnection(execute_error=queries.OperationalError('closed'))
        second = FakeConnection(rows=[{'id': 3}])
        connection_pool = Mock()
        connection_pool.getconn.side_effect = [first, second]

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            self.assertEqual(queries.query_db('SELECT id FROM users'), [{'id': 3}])

        self.assertEqual(connection_pool.getconn.call_count, 2)

    def test_select_is_attempted_no_more_than_twice(self):
        first = FakeConnection(execute_error=queries.OperationalError('closed'))
        second = FakeConnection(execute_error=queries.OperationalError('closed'))
        connection_pool = Mock()
        connection_pool.getconn.side_effect = [first, second]

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            with self.assertRaises(queries.OperationalError):
                queries.query_db('SELECT id FROM users')

        self.assertEqual(connection_pool.getconn.call_count, 2)
        self.assertEqual(connection_pool.putconn.call_count, 2)

    def test_write_and_commit_queries_are_not_retried(self):
        first = FakeConnection(execute_error=queries.OperationalError('closed'))
        connection_pool = Mock()
        connection_pool.getconn.return_value = first

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            with self.assertRaises(queries.OperationalError):
                queries.query_db('INSERT INTO users (username) VALUES (%s)', ('x',), commit=True)

        connection_pool.getconn.assert_called_once_with()
        connection_pool.putconn.assert_called_once_with(first, close=True)

    def test_direct_fallback_connection_is_closed_directly(self):
        connection = FakeConnection(rows=[{'id': 4}])

        with patch.object(queries, 'get_connection_pool', return_value=None), \
                patch.object(queries.psycopg2, 'connect', return_value=connection) as connect:
            self.assertEqual(queries.query_db('SELECT 1'), [{'id': 4}])

        connect.assert_called_once()
        self.assertEqual(connection.close_calls, 1)

    def test_retry_failure_propagates(self):
        first = FakeConnection(execute_error=queries.OperationalError('first'))
        second = FakeConnection(execute_error=queries.InterfaceError('second'))
        connection_pool = Mock()
        connection_pool.getconn.side_effect = [first, second]

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            with self.assertRaises(queries.InterfaceError):
                queries.query_db('SELECT 1')

    def test_auth_session_is_preserved_when_both_attempts_fail(self):
        first = FakeConnection(execute_error=queries.OperationalError('first'))
        second = FakeConnection(execute_error=queries.OperationalError('second'))
        connection_pool = Mock()
        connection_pool.getconn.side_effect = [first, second]
        client = app.test_client()

        with client.session_transaction() as stored_session:
            stored_session['user_id'] = 123
            stored_session['username'] = 'agent'
            stored_session.permanent = True

        with patch.object(queries, 'get_connection_pool', return_value=connection_pool):
            response = client.get('/success')

        self.assertEqual(response.status_code, 503)
        with client.session_transaction() as stored_session:
            self.assertEqual(stored_session['user_id'], 123)
            self.assertEqual(stored_session['username'], 'agent')


if __name__ == '__main__':
    unittest.main()
