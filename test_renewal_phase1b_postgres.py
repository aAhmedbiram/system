import os
import re
import uuid
from pathlib import Path

import pytest


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured; refusing to use DATABASE_URL",
)

SCHEMA_PREFIX = "renewal_phase1b_test_"
SCHEMA_PATTERN = re.compile(r"^renewal_phase1b_test_[0-9a-f]{32}$")


@pytest.fixture(scope="module")
def renewal_db():
    import psycopg2
    from psycopg2 import sql

    schema_name = f"{SCHEMA_PREFIX}{uuid.uuid4().hex}"
    assert SCHEMA_PATTERN.fullmatch(schema_name)
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = False
    schema_created = False
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}") .format(sql.Identifier(schema_name)))
            schema_created = True
            cur.execute(
                sql.SQL("SET search_path TO {}, public") .format(sql.Identifier(schema_name))
            )
            cur.execute(
                "CREATE TABLE members (id SERIAL PRIMARY KEY, name TEXT NOT NULL)"
            )
            cur.execute(
                """CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL
                )"""
            )
            migration = Path(__file__).parent / "system_app/migrations/add_renewal_workflow.sql"
            migration_sql = migration.read_text(encoding="utf-8")
            cur.execute(migration_sql)
            cur.execute(migration_sql)
        conn.commit()
        yield conn, schema_name
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            if schema_created:
                with conn.cursor() as cur:
                    assert SCHEMA_PATTERN.fullmatch(schema_name)
                    cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
                conn.commit()
        finally:
            conn.close()


def _connection(renewal_db):
    return renewal_db[0]


def _schema(renewal_db):
    return renewal_db[1]


def _seed_member(renewal_db, member_id=910001):
    conn = _connection(renewal_db)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO members (id, name) VALUES (%s, %s) "
            "ON CONFLICT (id) DO NOTHING",
            (member_id, f"Phase 1B Test Member {member_id}"),
        )
    conn.commit()


def _seed_user(renewal_db, user_id=910001):
    conn = _connection(renewal_db)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, username, email, password) VALUES "
            "(%s, %s, %s, 'test') ON CONFLICT (id) DO NOTHING",
            (
                user_id,
                f"renewal_phase1b_owner_{user_id}",
                f"renewal_phase1b_owner_{user_id}@test.invalid",
            ),
        )
    conn.commit()


def _seed_case(
    renewal_db,
    member_id=910001,
    cycle_end_date="2026-10-01",
    owner_user_id=910001,
):
    _seed_member(renewal_db, member_id)
    if owner_user_id is not None:
        _seed_user(renewal_db, owner_user_id)

    conn = _connection(renewal_db)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO renewal_cases (member_id, cycle_end_date, owner_user_id) "
            "VALUES (%s, %s, %s) "
            "ON CONFLICT (member_id, cycle_end_date) DO UPDATE "
            "SET owner_user_id = EXCLUDED.owner_user_id "
            "RETURNING id",
            (member_id, cycle_end_date, owner_user_id),
        )
        case_id = cur.fetchone()[0]
    conn.commit()
    return case_id


def _expect_db_error(conn, exception_type, query, params=()):
    with pytest.raises(exception_type):
        with conn.cursor() as cur:
            cur.execute(query, params)
    conn.rollback()


def test_migration_tables_indexes_and_sensitive_columns(renewal_db):
    conn = _connection(renewal_db)
    schema_name = _schema(renewal_db)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_name LIKE 'renewal_%%'",
            (schema_name,),
        )
        assert {row[0] for row in cur.fetchall()} >= {
            "renewal_cases", "renewal_follow_ups", "renewal_assignment_events"
        }
        cur.execute(
            "SELECT table_name, column_name FROM information_schema.columns "
            "WHERE table_schema = %s AND table_name LIKE 'renewal_%%'",
            (schema_name,),
        )
        columns = {(table, column) for table, column in cur.fetchall()}
        assert not any(column in {"phone", "message", "token", "crm_lead_id"} for _, column in columns)
        cur.execute(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = %s AND indexname LIKE 'idx_renewal_%%'",
            (schema_name,),
        )
        indexes = {row[0] for row in cur.fetchall()}
    assert {
        "idx_renewal_cases_owner_status_cycle",
        "idx_renewal_cases_status_next_follow_up_cycle",
        "idx_renewal_follow_ups_case_created",
        "idx_renewal_assignment_events_case_created",
    } <= indexes


def test_migration_is_executed_twice_in_the_isolated_schema(renewal_db):
    # The module fixture executes the exact migration twice before yielding.
    conn = _connection(renewal_db)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) FROM information_schema.tables "
            "WHERE table_schema = current_schema() "
            "AND table_name IN (%s, %s, %s)",
            ("renewal_cases", "renewal_follow_ups", "renewal_assignment_events"),
        )
        assert cur.fetchone()[0] == 3


def test_cycle_and_operation_uniqueness(renewal_db):
    conn = _connection(renewal_db)
    case_id = _seed_case(renewal_db)
    _expect_db_error(
        conn,
        __import__("psycopg2").errors.UniqueViolation,
        "INSERT INTO renewal_cases (member_id, cycle_end_date) VALUES (910001, DATE '2026-10-01')",
    )
    operation_id = str(uuid.uuid4())
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO renewal_follow_ups "
            "(renewal_case_id, contact_method, contact_result, client_operation_id) "
            "VALUES (%s, 'CALL', 'NO_ANSWER', %s)",
            (case_id, operation_id),
        )
    conn.commit()
    _expect_db_error(
        conn,
        __import__("psycopg2").errors.UniqueViolation,
        "INSERT INTO renewal_follow_ups "
        "(renewal_case_id, contact_method, contact_result, client_operation_id) "
        "VALUES (%s, 'CALL', 'NO_ANSWER', %s)",
        (case_id, operation_id),
    )


@pytest.mark.parametrize("status", ["FOLLOW_UP_DUE", "RENEWED", "LOST", "INVALID"])
def test_invalid_operational_statuses_are_rejected(renewal_db, status):
    import psycopg2

    conn = _connection(renewal_db)
    member_id = 910010 + len(status)
    _seed_member(renewal_db, member_id)
    _expect_db_error(
        conn,
        psycopg2.errors.CheckViolation,
        "INSERT INTO renewal_cases (member_id, cycle_end_date, operational_status) "
        "VALUES (%s, %s, %s)",
        (member_id, f"2026-11-{len(status):02d}", status),
    )


def test_invalid_contact_method_and_result_are_rejected(renewal_db):
    import psycopg2

    conn = _connection(renewal_db)
    case_id = _seed_case(renewal_db, member_id=910020, cycle_end_date="2026-11-20")
    _expect_db_error(
        conn,
        psycopg2.errors.CheckViolation,
        "INSERT INTO renewal_follow_ups "
        "(renewal_case_id, contact_method, contact_result, client_operation_id) "
        "VALUES (%s, 'WHATSAPP', 'REACHED', %s)",
        (case_id, str(uuid.uuid4())),
    )
    _expect_db_error(
        conn,
        psycopg2.errors.CheckViolation,
        "INSERT INTO renewal_follow_ups "
        "(renewal_case_id, contact_method, contact_result, client_operation_id) "
        "VALUES (%s, 'CALL', 'INVALID', %s)",
        (case_id, str(uuid.uuid4())),
    )


@pytest.mark.parametrize("version", [0, -1])
def test_case_version_must_be_positive(renewal_db, version):
    import psycopg2

    conn = _connection(renewal_db)
    member_id = 910030 + abs(version)
    _seed_member(renewal_db, member_id)
    _expect_db_error(
        conn,
        psycopg2.errors.CheckViolation,
        "INSERT INTO renewal_cases (member_id, cycle_end_date, version) VALUES (%s, %s, %s)",
        (member_id, f"2026-12-{abs(version) + 1:02d}", version),
    )


def test_foreign_keys_and_historical_user_set_null(renewal_db):
    import psycopg2

    conn = _connection(renewal_db)
    _expect_db_error(
        conn,
        psycopg2.errors.ForeignKeyViolation,
        "INSERT INTO renewal_cases (member_id, cycle_end_date) VALUES (999991, DATE '2026-12-01')",
    )
    _seed_member(renewal_db, 910041)
    _expect_db_error(
        conn,
        psycopg2.errors.ForeignKeyViolation,
        "INSERT INTO renewal_cases (member_id, cycle_end_date, owner_user_id) "
        "VALUES (910041, DATE '2026-12-02', 999992)",
    )
    _expect_db_error(
        conn,
        psycopg2.errors.ForeignKeyViolation,
        "INSERT INTO renewal_follow_ups "
        "(renewal_case_id, contact_method, contact_result, client_operation_id) "
        "VALUES (999993, 'CALL', 'REACHED', %s)",
        (str(uuid.uuid4()),),
    )
    _expect_db_error(
        conn,
        psycopg2.errors.ForeignKeyViolation,
        "INSERT INTO renewal_assignment_events (renewal_case_id, reason) "
        "VALUES (999994, 'phase1b-test:invalid-case')",
    )

    case_id = _seed_case(renewal_db, member_id=910043, cycle_end_date="2026-12-03", owner_user_id=910043)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO renewal_assignment_events "
            "(renewal_case_id, previous_owner_user_id, new_owner_user_id, changed_by_user_id, reason) "
            "VALUES (%s, 910043, 910043, 910043, 'phase1b-test:set-null')",
            (case_id,),
        )
        cur.execute(
            "INSERT INTO renewal_follow_ups "
            "(renewal_case_id, performed_by_user_id, contact_method, contact_result, client_operation_id) "
            "VALUES (%s, 910043, 'CALL', 'REACHED', %s)",
            (case_id, str(uuid.uuid4())),
        )
        cur.execute("DELETE FROM users WHERE id = 910043")
    conn.commit()
    with conn.cursor() as cur:
        cur.execute("SELECT owner_user_id FROM renewal_cases WHERE id = %s", (case_id,))
        assert cur.fetchone()[0] is None
        cur.execute("SELECT performed_by_user_id FROM renewal_follow_ups WHERE renewal_case_id = %s", (case_id,))
        assert cur.fetchone()[0] is None
        cur.execute("SELECT previous_owner_user_id, new_owner_user_id, changed_by_user_id "
                    "FROM renewal_assignment_events WHERE renewal_case_id = %s", (case_id,))
        assert cur.fetchone() == (None, None, None)
