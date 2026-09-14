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


class TestQueryPoolResilience(unittest.TestCase):
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
