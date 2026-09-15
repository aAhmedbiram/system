import os
import threading
import unittest
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

import psycopg2
import pytz

from system_app import queries


TEST_DATABASE_URL = os.environ.get('TEST_DATABASE_URL')


@unittest.skipUnless(TEST_DATABASE_URL, 'TEST_DATABASE_URL is not configured; production DATABASE_URL is never used')
class TestAttendanceOfflinePostgresPhase1(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.connection = psycopg2.connect(TEST_DATABASE_URL)
        cls.connection.autocommit = True
        with cls.connection.cursor() as cursor:
            cursor.execute('CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, username TEXT UNIQUE, email TEXT UNIQUE, password TEXT)')
            cursor.execute('CREATE TABLE IF NOT EXISTS members (id SERIAL PRIMARY KEY, name TEXT, end_date TEXT, membership_status TEXT)')
            cursor.execute('CREATE TABLE IF NOT EXISTS attendance (num SERIAL PRIMARY KEY, member_id INTEGER, name TEXT, end_date TEXT, membership_status TEXT, attendance_time TEXT, attendance_date TEXT, day TEXT)')
            cursor.execute('''CREATE TABLE IF NOT EXISTS offline_attendance_operations (
                client_operation_id UUID PRIMARY KEY, member_id INTEGER,
                user_id INTEGER, username TEXT, server_business_date DATE NOT NULL,
                status TEXT NOT NULL, result_code TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                synced_at TIMESTAMPTZ,
                CHECK (status IN ('processing', 'processed'))
            )''')

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()

    def setUp(self):
        self.member_id = None
        self.user_id = None
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO members (name, end_date, membership_status) VALUES ('Phase1 Member', '2099-01-01', 'VAL') RETURNING id")
            self.member_id = cursor.fetchone()[0]
            username = f'phase1-{uuid4()}'
            cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, 'unused') RETURNING id", (username, f'{username}@test.invalid'))
            self.user_id = cursor.fetchone()[0]
            self.username = username

    def tearDown(self):
        with self.connection.cursor() as cursor:
            cursor.execute('DELETE FROM offline_attendance_operations WHERE user_id = %s', (self.user_id,))
            cursor.execute('DELETE FROM attendance WHERE member_id = %s', (self.member_id,))
            cursor.execute('DELETE FROM members WHERE id = %s', (self.member_id,))
            cursor.execute('DELETE FROM users WHERE id = %s', (self.user_id,))

    def operation(self, operation_id=None, member_id=None, captured=None):
        captured = captured or pytz.timezone('Africa/Cairo').localize(datetime.now())
        return {
            'client_operation_id': operation_id or str(uuid4()),
            'member_id': member_id or self.member_id,
            'server_business_date': captured.date(),
            'attendance_at': captured,
        }

    def process(self, operations, user_id=None, username=None):
        with patch.object(queries, 'get_connection_pool', return_value=None), patch.object(
            queries, 'get_database_url', return_value=TEST_DATABASE_URL,
        ):
            return queries.process_offline_attendance_operations(
                operations, user_id or self.user_id, username or self.username,
            )

    def test_first_insert_and_same_uuid_replay(self):
        operation = self.operation()
        self.assertEqual(self.process([operation])[0]['result_code'], 'synced')
        replay = self.process([operation])[0]
        self.assertEqual((replay['result_code'], replay['replayed']), ('synced', True))

    def test_different_uuid_duplicate_and_business_date(self):
        captured = pytz.timezone('Africa/Cairo').localize(datetime(2026, 9, 15, 23, 59, 59))
        self.assertEqual(self.process([self.operation(captured=captured)])[0]['result_code'], 'synced')
        second = self.process([self.operation(captured=captured)])[0]
        self.assertEqual(second['result_code'], 'duplicate_attendance')
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT attendance_date, attendance_time, day FROM attendance WHERE member_id = %s', (self.member_id,))
            self.assertEqual(cursor.fetchone(), ('2026-09-15', '23:59:59', 'Tuesday'))

    def test_capture_before_midnight_sync_after_midnight_keeps_date(self):
        captured = pytz.timezone('Africa/Cairo').localize(datetime(2026, 9, 15, 23, 59, 59))
        self.assertEqual(self.process([self.operation(captured=captured)])[0]['result_code'], 'synced')
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT attendance_date FROM attendance WHERE member_id = %s', (self.member_id,))
            self.assertEqual(cursor.fetchone()[0], '2026-09-15')

    def test_two_simultaneous_offline_operations_are_serialized(self):
        operations = [self.operation(), self.operation()]
        results, errors = [], []

        def worker(operation):
            try:
                results.extend(self.process([operation]))
            except Exception as error:
                errors.append(error)

        threads = [threading.Thread(target=worker, args=(operation,)) for operation in operations]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertFalse(errors)
        self.assertEqual(sorted(item['result_code'] for item in results), ['duplicate_attendance', 'synced'])

    def test_cross_user_replay_is_unauthorized(self):
        operation = self.operation()
        self.assertEqual(self.process([operation])[0]['result_code'], 'synced')
        other_id = None
        with self.connection.cursor() as cursor:
            cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, 'unused') RETURNING id", (f'other-{uuid4()}', f'{uuid4()}@test.invalid'))
            other_id = cursor.fetchone()[0]
        try:
            self.assertEqual(self.process([operation], user_id=other_id, username='other')[0]['result_code'], 'unauthorized')
        finally:
            with self.connection.cursor() as cursor:
                cursor.execute('DELETE FROM users WHERE id = %s', (other_id,))

    def test_transaction_rollback_leaves_no_idempotency_row(self):
        operation = self.operation()
        with self.assertRaises(KeyError):
            self.process([{'client_operation_id': operation['client_operation_id'], 'member_id': self.member_id}])
        with self.connection.cursor() as cursor:
            cursor.execute('SELECT COUNT(*) FROM offline_attendance_operations WHERE client_operation_id = %s', (operation['client_operation_id'],))
            self.assertEqual(cursor.fetchone()[0], 0)

    def test_existing_table_contains_required_columns(self):
        with self.connection.cursor() as cursor:
            cursor.execute("SELECT column_name FROM information_schema.columns WHERE table_name = 'offline_attendance_operations'")
            columns = {row[0] for row in cursor.fetchall()}
        self.assertTrue({'client_operation_id', 'member_id', 'user_id', 'server_business_date', 'status', 'result_code'} <= columns)


if __name__ == '__main__':
    unittest.main()
