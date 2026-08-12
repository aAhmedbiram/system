import unittest
import datetime
import threading
from system_app.app import app
from system_app.queries import query_db
from system_app.crm.queries import run_in_transaction
from system_app.member_services import (
    create_member_in_transaction, renew_member_in_transaction,
    generate_invoice_number_in_transaction
)

class TestMemberTransactionServices(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True

        # Cleanup database records
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)

    def tearDown(self):
        query_db("DELETE FROM invoices", commit=True)
        query_db("DELETE FROM renewal_logs", commit=True)
        query_db("DELETE FROM member_logs", commit=True)
        query_db("DELETE FROM action_logs", commit=True)
        query_db("DELETE FROM members WHERE name LIKE 'Test%%'", commit=True)

    # ==========================================
    # A. TRANSACTION HELPER TESTS
    # ==========================================

    def test_1_callback_success_commits(self):
        """TEST 1: Successful callback execution commits changes."""
        def callback(cur):
            cur.execute(
                "INSERT INTO members (name, phone) VALUES ('Test Success', '1111') RETURNING id;"
            )
            return cur.fetchone()['id']

        member_id = run_in_transaction(callback)
        self.assertIsNotNone(member_id)

        # Verify in DB (outside transaction)
        member = query_db("SELECT * FROM members WHERE id = %s", (member_id,), one=True)
        self.assertEqual(member['name'], 'Test Success')

    def test_2_callback_exception_rolls_back(self):
        """TEST 2: Callback exception triggers transaction rollback."""
        def callback(cur):
            cur.execute(
                "INSERT INTO members (name, phone) VALUES ('Test Fail Rollback', '2222') RETURNING id;"
            )
            raise ValueError("Forced error inside transaction callback")

        with self.assertRaises(ValueError):
            run_in_transaction(callback)

        # Verify no member was created
        member = query_db("SELECT * FROM members WHERE name = 'Test Fail Rollback'", one=True)
        self.assertIsNone(member)

    def test_3_4_returning_value_consumed_and_returned(self):
        """TEST 3-4: Verify callback return value is correctly returned."""
        def callback(cur):
            cur.execute("SELECT 42 as num;")
            return cur.fetchone()['num']

        res = run_in_transaction(callback)
        self.assertEqual(res, 42)

    # ==========================================
    # B. NEW MEMBER SERVICES TESTS
    # ==========================================

    def test_5_to_9_create_member_success(self):
        """TEST 5-9: New member creation stores correct fields, creates invoice, and writes logs."""
        data = {
            "name": "Test Member Creation",
            "phone": "3333",
            "national_id": "12345678901234",
            "gender": "Male",
            "birthdate": "1990-01-01",
            "starting_date": "2026-08-15",
            "membership_packages": "3 Months",
            "membership_fees": 1200.00,
            "comment": "Happy customer"
        }

        def run_create(cur):
            return create_member_in_transaction(cur, data, 'crm_agent')

        res = run_in_transaction(run_create)
        member_id = res['member_id']

        # Assertions on member table
        member = query_db("SELECT * FROM members WHERE id = %s", (member_id,), one=True)
        self.assertEqual(member['name'], 'Test member creation')
        self.assertEqual(member['phone'], '3333')
        self.assertEqual(member['invitations'], 3)
        self.assertEqual(member['membership_status'], 'VAL')

        # Assertions on invoice table
        invoice = query_db("SELECT * FROM invoices WHERE member_id = %s", (member_id,), one=True)
        self.assertIsNotNone(invoice)
        self.assertEqual(invoice['invoice_type'], 'new_member')
        self.assertEqual(invoice['amount'], 1200.00)
        self.assertEqual(invoice['created_by'], 'crm_agent')

        # Assertions on action logs
        log = query_db("SELECT * FROM action_logs WHERE member_id = %s", (member_id,), one=True)
        self.assertIsNotNone(log)
        self.assertEqual(log['performed_by'], 'crm_agent')

    def test_10_forced_invoice_failure_rolls_back_all(self):
        """TEST 10: Failures in invoicing cause database rollback on member insertion."""
        data = {
            "name": "Test Fail Invoice Member",
            "phone": "4444",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }

        def run_create_with_invoice_fail(cur):
            res = create_member_in_transaction(cur, data)
            # Force integrity error by inserting invoice with a duplicate invoice number manually
            cur.execute(
                "INSERT INTO invoices (invoice_number, member_name, invoice_type, amount, invoice_date) "
                "VALUES (%s, 'dummy', 'new_member', 100, CURRENT_DATE)", (res['invoice_number'],)
            )
            return res

        with self.assertRaises(Exception):
            run_in_transaction(run_create_with_invoice_fail)

        # Verify no member was created
        member = query_db("SELECT * FROM members WHERE name = 'Test Fail Invoice Member'", one=True)
        self.assertIsNone(member)

    def test_11_forced_log_failure_rolls_back_all(self):
        """TEST 11: Failures in logging cause database rollback on member and invoice inserts."""
        data = {
            "name": "Test Fail Log Member",
            "phone": "5555",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }

        def run_create_with_log_fail(cur):
            res = create_member_in_transaction(cur, data)
            # Force violation constraint error in action logs
            cur.execute(
                "INSERT INTO action_logs (action_type, performed_by) VALUES (NULL, 'agent')"
            )
            return res

        with self.assertRaises(Exception):
            run_in_transaction(run_create_with_log_fail)

        # Verify no member was created
        member = query_db("SELECT * FROM members WHERE name = 'Test Fail Log Member'", one=True)
        self.assertIsNone(member)

    def test_12_duplicate_phone_national_id_fails(self):
        """TEST 12: Duplicate phone or national ID triggers validation errors."""
        data1 = {
            "name": "Test Original",
            "phone": "6666",
            "national_id": "11111111111111",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }
        data2 = {
            "name": "Test Duplicate",
            "phone": "6666", # Duplicate phone
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }

        # Create first
        run_in_transaction(lambda cur: create_member_in_transaction(cur, data1))

        # Try second
        with self.assertRaises(ValueError):
            run_in_transaction(lambda cur: create_member_in_transaction(cur, data2))

    # ==========================================
    # C. CONCURRENCY TESTS
    # ==========================================

    def test_13_simultaneous_member_inserts(self):
        """TEST 13: Multiple concurrent member insertions do not collide or duplicate primary keys."""
        errors = []

        def insert_worker(phone):
            try:
                data = {
                    "name": f"Test Worker {phone}",
                    "phone": phone,
                    "membership_packages": "1 Month",
                    "starting_date": "2026-08-15"
                }
                run_in_transaction(lambda cur: create_member_in_transaction(cur, data))
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=insert_worker, args=(str(1000 + i),)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Concurrent inserts raised errors: {errors}")

    def test_15_invoice_number_generation_does_not_collide(self):
        """TEST 15: Concurrent invoice number generation locks table and returns unique sequence values."""
        invoice_numbers = []
        errors = []

        def invoice_worker():
            try:
                def callback(cur):
                    num = generate_invoice_number_in_transaction(cur)
                    cur.execute(
                        "INSERT INTO invoices (invoice_number, member_name, invoice_type, amount, invoice_date) "
                        "VALUES (%s, 'dummy', 'new_member', 100, CURRENT_DATE)", (num,)
                    )
                    return num
                num = run_in_transaction(callback)
                invoice_numbers.append(num)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=invoice_worker) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0, f"Invoice worker raised errors: {errors}")
        self.assertEqual(len(invoice_numbers), len(set(invoice_numbers)), "Collided invoice numbers generated!")

    # ==========================================
    # D. RENEWAL / REACTIVATION TESTS
    # ==========================================

    def test_16_to_20_renew_member_success(self):
        """TEST 16-20: Renewal updates package/dates, resets freeze flags, writes renewal_logs and invoice."""
        # Create member first
        setup_data = {
            "name": "Test Renew Member",
            "phone": "7777",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }
        res_setup = run_in_transaction(lambda cur: create_member_in_transaction(cur, setup_data))
        member_id = res_setup['member_id']

        # Hardcode freeze_used to True
        query_db("UPDATE members SET freeze_used = TRUE WHERE id = %s", (member_id,), commit=True)

        # Renew member
        renew_data = {
            "starting_date": "2026-09-15",
            "membership_packages": "3 Months"
        }
        res_renew = run_in_transaction(lambda cur: renew_member_in_transaction(cur, member_id, renew_data, 'manager_user'))

        # Assertions on member table updates
        member = query_db("SELECT * FROM members WHERE id = %s", (member_id,), one=True)
        self.assertEqual(member['membership_packages'], '3 Months')
        self.assertEqual(member['starting_date'], '2026-09-15')
        self.assertFalse(member['freeze_used']) # Reset successfully

        # Assertions on renewal log
        rlog = query_db("SELECT * FROM renewal_logs WHERE member_id = %s", (member_id,), one=True)
        self.assertIsNotNone(rlog)
        self.assertEqual(rlog['package_name'], '3 Months')
        self.assertEqual(rlog['edited_by'], 'manager_user')

        # Assertions on invoice table
        invoice = query_db("SELECT * FROM invoices WHERE member_id = %s AND invoice_type = 'renewal'", (member_id,), one=True)
        self.assertIsNotNone(invoice)

    def test_21_forced_renewal_failure_rolls_back_all(self):
        """TEST 21: Failure in renewal logging rolls back member renewals."""
        setup_data = {
            "name": "Test Renew Fail Member",
            "phone": "8888",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }
        res_setup = run_in_transaction(lambda cur: create_member_in_transaction(cur, setup_data))
        member_id = res_setup['member_id']

        renew_data = {
            "starting_date": "2026-09-15",
            "membership_packages": "3 Months"
        }

        def run_renew_with_log_fail(cur):
            renew_member_in_transaction(cur, member_id, renew_data)
            # Force unique constraint violation on member_logs (mock error)
            cur.execute(
                "INSERT INTO member_logs (member_id, field_name, old_value, new_value) VALUES (NULL, NULL, NULL, NULL)"
            )

        with self.assertRaises(Exception):
            run_in_transaction(run_renew_with_log_fail)

        # Verify member values did NOT change (rolled back to original 1 Month)
        member = query_db("SELECT * FROM members WHERE id = %s", (member_id,), one=True)
        self.assertEqual(member['membership_packages'], '1 Month')

    def test_22_member_row_locking(self):
        """TEST 22: Renewal row lock blocks concurrent edits on same member."""
        setup_data = {
            "name": "Test Lock Member",
            "phone": "9999",
            "membership_packages": "1 Month",
            "starting_date": "2026-08-15"
        }
        res_setup = run_in_transaction(lambda cur: create_member_in_transaction(cur, setup_data))
        member_id = res_setup['member_id']

        # We start a transaction in Thread A and hold the lock
        import time
        thread_a_started = threading.Event()
        thread_a_done = threading.Event()

        def worker_a():
            def callback(cur):
                cur.execute("SELECT * FROM members WHERE id = %s FOR UPDATE", (member_id,))
                thread_a_started.set()
                time.sleep(0.5) # Hold lock

            run_in_transaction(callback)
            thread_a_done.set()

        t_a = threading.Thread(target=worker_a)
        t_a.start()

        thread_a_started.wait()

        # Thread B tries to renew the same member concurrently - must be blocked until A commits
        start_time = time.time()

        def worker_b():
            renew_data = {
                "starting_date": "2026-09-15",
                "membership_packages": "3 Months"
            }
            run_in_transaction(lambda cur: renew_member_in_transaction(cur, member_id, renew_data))

        worker_b()
        duration = time.time() - start_time

        # Verify that B waited for A to finish (duration > 0.4 seconds)
        self.assertGreaterEqual(duration, 0.4)
        t_a.join()

if __name__ == '__main__':
    unittest.main()
