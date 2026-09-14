import os
import threading
import unittest
import unittest.mock
from datetime import date
from pathlib import Path
from uuid import uuid4

import psycopg2

from system_app import queries


TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL')


@unittest.skipUnless(TEST_DATABASE_URL, 'TEST_DATABASE_URL is not configured; production DATABASE_URL is never used')
class TestOfflineAttendancePostgres(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = psycopg2.connect(TEST_DATABASE_URL)
        cls.connection.autocommit = True
        with cls.connection.cursor() as cursor:
            cursor.execute("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE, password TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS members (id SERIAL PRIMARY KEY, name TEXT, end_date TEXT, membership_status TEXT)")
            cursor.execute("CREATE TABLE IF NOT EXISTS attendance (num SERIAL PRIMARY KEY, member_id INTEGER, name TEXT, end_date TEXT, membership_status TEXT, attendance_time TEXT, attendance_date TEXT, day TEXT)")
            cursor.execute(Path('system_app/migrations/add_offline_attendance_sync.sql').read_text())

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def setUp(self):
        self.user_id = None
        self.member_id = None
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO members (name, end_date, membership_status) VALUES ('Offline Test Member', '2099-01-01', 'VAL') RETURNING id")
            self.member_id = cursor.fetchone()[0]
            self.username = f'offline-test-{uuid4()}'
            cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, 'not-used') RETURNING id", (self.username, f'{self.username}@test.invalid'))
            self.user_id = cursor.fetchone()[0]

    def tearDown(self):
        with self.connection.cursor() as cursor:
            cursor.execute('DELETE FROM offline_attendance_operations WHERE user_id = %s', (self.user_id,))
            cursor.execute('DELETE FROM attendance WHERE member_id = %s', (self.member_id,))
            cursor.execute('DELETE FROM members WHERE id = %s', (self.member_id,))
            cursor.execute('DELETE FROM users WHERE id = %s', (self.user_id,))

    def operation(self, member_id=None, operation_id=None):
        return {
            'client_operation_id': operation_id or str(uuid4()),
            'member_id': member_id or self.member_id,
            'server_business_date': date.today(),
            'attendance_time': '10:00:00',
            'attendance_day': 'Monday',
        }

    def run_processor(self, operations):
        with unittest.mock.patch.object(queries, 'get_connection_pool', return_value=None), \
                unittest.mock.patch.object(queries, 'get_database_url', return_value=TEST_DATABASE_URL):
            return queries.process_offline_attendance_operations(operations, self.user_id, self.username)

    def test_first_replay_and_different_idempotency(self):
        first = self.operation()
        self.assertEqual(self.run_processor([first])[0]['result_code'], 'synced')
        replay = self.run_processor([first])[0]
        self.assertEqual((replay['result_code'], replay['replayed']), ('synced', True))
        self.assertEqual(self.run_processor([self.operation(operation_id=str(uuid4()))])[0]['result_code'], 'duplicate_attendance')
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM attendance WHERE member_id = %s', (self.member_id,))
            self.assertEqual(cursor.fetchone()[0], 1)
            cursor.execute('SELECT COUNT(*) FROM offline_attendance_operations WHERE user_id = %s', (self.user_id,))
            self.assertEqual(cursor.fetchone()[0], 2)

    def test_terminal_rejections_replay_identically(self):
        inactive_id = self.connection.cursor()
        with inactive_id as cursor:
            cursor.execute("INSERT INTO members (name, end_date, membership_status) VALUES ('Inactive', '2000-01-01', 'EXPIRED') RETURNING id")
            inactive_member = cursor.fetchone()[0]
        try:
            for member_id, expected in ((999999999, 'invalid_member'), (inactive_member, 'inactive_membership')):
                operation = self.operation(member_id=member_id)
                self.assertEqual(self.run_processor([operation])[0]['result_code'], expected)
                replay = self.run_processor([operation])[0]
                self.assertEqual((replay['result_code'], replay['replayed']), (expected, True))
        finally:
            with self.connection.cursor() as cursor:
                cursor.execute('DELETE FROM members WHERE id = %s', (inactive_member,))

    def test_mixed_batch_and_transaction_rollback(self):
        first = self.operation()
        invalid = self.operation(member_id=999999999)
        results = self.run_processor([first, invalid])
        self.assertEqual([item['result_code'] for item in results], ['synced', 'invalid_member'])
        with self.assertRaises(KeyError):
            self.run_processor([self.operation(operation_id=str(uuid4())), {'client_operation_id': str(uuid4())}])
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM attendance WHERE member_id = %s', (self.member_id,))
            self.assertEqual(cursor.fetchone()[0], 1)

    def test_concurrent_same_member_day_is_serialized(self):
        operations = [self.operation(operation_id=str(uuid4())), self.operation(operation_id=str(uuid4()))]
        results = []
        errors = []
        def worker(operation):
            try:
                results.extend(self.run_processor([operation]))
            except Exception as error:
                errors.append(error)
        threads = [threading.Thread(target=worker, args=(operation,)) for operation in operations]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertFalse(errors)
        self.assertEqual(sorted(item['result_code'] for item in results), ['duplicate_attendance', 'synced'])


if __name__ == '__main__':
    unittest.main()
