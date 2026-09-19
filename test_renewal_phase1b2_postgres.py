import os
import re
import threading
import uuid
from datetime import timedelta
from pathlib import Path

import pytest


TEST_DATABASE_URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is not configured; refusing to use DATABASE_URL",
)

SCHEMA_PREFIX = "renewal_phase1b2_test_"
SCHEMA_PATTERN = re.compile(r"^renewal_phase1b2_test_[0-9a-f]{32}$")


@pytest.fixture
def renewal_db(monkeypatch):
    import psycopg2
    from psycopg2 import sql
    from psycopg2.extras import Json

    from system_app.func import get_cairo_date
    from system_app.renewal import transactions

    schema_name = f"{SCHEMA_PREFIX}{uuid.uuid4().hex}"
    assert SCHEMA_PATTERN.fullmatch(schema_name)
    conn = psycopg2.connect(TEST_DATABASE_URL)
    conn.autocommit = False
    schema_created = False

    class SingleConnectionPool:
        def getconn(self):
            return conn

        def putconn(self, returned, close=False):
            assert returned is conn
            if close:
                returned.close()

    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}" ).format(sql.Identifier(schema_name)))
            schema_created = True
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema_name)))
            cur.execute(
                """
                CREATE TABLE members (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL,
                    end_date TEXT,
                    membership_status TEXT,
                    membership_packages TEXT
                )
                """
            )
            cur.execute(
                """
                CREATE TABLE users (
                    id SERIAL PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password TEXT NOT NULL,
                    is_approved BOOLEAN DEFAULT FALSE,
                    permissions JSONB
                )
                """
            )
            migration = Path(__file__).parent / "system_app/migrations/add_renewal_workflow.sql"
            migration_sql = migration.read_text(encoding="utf-8")
            cur.execute(migration_sql)
            cur.execute(migration_sql)
        conn.commit()
        monkeypatch.setattr(transactions, "get_connection_pool", lambda: SingleConnectionPool())
        yield conn, get_cairo_date(), schema_name
    finally:
        try:
            conn.rollback()
        except Exception:
            pass
        if schema_created:
            try:
                with conn.cursor() as cur:
                    assert SCHEMA_PATTERN.fullmatch(schema_name)
                    cur.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema_name)))
                conn.commit()
            except Exception:
                conn.rollback()
        conn.close()


def _seed_user(conn, user_id, username, permissions, approved=True):
    from psycopg2.extras import Json

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, username, email, password, is_approved, permissions) "
            "VALUES (%s, %s, %s, 'test', %s, %s)",
            (user_id, username, f"{username}@test.invalid", approved, Json(permissions)),
        )
    conn.commit()


def _seed_member(conn, member_id, end_date, name=None, status="ACTIVE"):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO members (id, name, end_date, membership_status) "
            "VALUES (%s, %s, %s, %s)",
            (member_id, name or f"Member {member_id}", end_date, status),
        )
    conn.commit()


def test_assignment_transaction_creates_case_event_and_version(renewal_db):
    from system_app.renewal.queries import assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 1, "actor", {"renewal_center_manager": True})
    _seed_user(conn, 2, "owner", {"renewal_center_view": True})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO members (id, name, end_date, membership_status) VALUES (7, 'Member', %s, 'ACTIVE')",
            ((today + timedelta(days=5)).isoformat(),),
        )
    conn.commit()

    result = assign_renewal_case(
        actor_user_id=1,
        member_id=7,
        expected_version=0,
        owner_user_id=2,
    )
    assert result["changed"] is True
    assert result["case"]["owner_user_id"] == 2
    assert result["case"]["operational_status"] == "OPEN"
    assert result["case"]["version"] == 2

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM renewal_cases WHERE member_id = 7")
        assert cur.fetchone()[0] == 1
        cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
        assert cur.fetchone()[0] == 1


def test_same_owner_is_noop_and_stale_version_is_rejected(renewal_db):
    from psycopg2.extras import Json
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 3, "owner_three", {"renewal_center_view": True})
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, username, email, password, is_approved, permissions) "
            "VALUES (4, 'owner_four', 'owner_four@test.invalid', 'test', TRUE, %s)",
            (Json({"renewal_center_view": True}),),
        )
        cur.execute(
            "INSERT INTO members (id, name, end_date, membership_status) VALUES (8, 'Member Two', %s, 'ACTIVE')",
            ((today + timedelta(days=6)).isoformat(),),
        )
    conn.commit()

    first = assign_renewal_case(actor_user_id=3, member_id=8, expected_version=0, owner_user_id=3)
    replay = assign_renewal_case(actor_user_id=3, member_id=8, expected_version=0, owner_user_id=3)
    assert replay["changed"] is False
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM renewal_assignment_events WHERE renewal_case_id = %s", (first["case"]["id"],))
        assert cur.fetchone()[0] == 1

    reassigned = assign_renewal_case(actor_user_id=3, member_id=8, expected_version=2, owner_user_id=4)
    assert reassigned["case"]["version"] == 3
    with pytest.raises(RenewalAssignmentError) as exc_info:
        assign_renewal_case(actor_user_id=3, member_id=8, expected_version=2, owner_user_id=3)
    assert exc_info.value.code == "assignment_conflict"


def test_invalid_assignees_do_not_create_case_or_event(renewal_db):
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 10, "actor", {"renewal_center_manager": True})
    _seed_user(conn, 11, "unapproved", {"renewal_center_view": True}, approved=False)
    _seed_user(conn, 12, "no_view", {})
    _seed_member(conn, 10, (today + timedelta(days=5)).isoformat())

    for owner_id in (999, 11, 12):
        with pytest.raises(RenewalAssignmentError) as exc_info:
            assign_renewal_case(
                actor_user_id=10,
                member_id=10,
                expected_version=0,
                owner_user_id=owner_id,
            )
        assert exc_info.value.code == "invalid_assignee"

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM renewal_cases")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
        assert cur.fetchone()[0] == 0


def test_assignee_candidates_match_renewal_bypass_policy(renewal_db, monkeypatch):
    from psycopg2.extras import RealDictCursor
    from system_app.renewal import queries as renewal_queries

    conn, _today, _schema = renewal_db
    _seed_user(conn, 70, "rino", {}, approved=False)
    _seed_user(conn, 71, "approved_viewer", {"renewal_center_view": True})
    _seed_user(conn, 72, "approved_super", {"super_admin": True})
    _seed_user(conn, 73, "unapproved_viewer", {"renewal_center_view": True}, approved=False)
    _seed_user(conn, 74, "unapproved_super", {"super_admin": True}, approved=False)
    _seed_user(conn, 75, "approved_plain", {})

    def isolated_query_db(query, params=(), one=False):
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params)
            rows = cur.fetchall()
        return (dict(rows[0]) if rows else None) if one else [dict(row) for row in rows]

    monkeypatch.setattr(renewal_queries, "query_db", isolated_query_db)
    candidates = renewal_queries.get_renewal_assignees()

    assert candidates == [
        {"id": 72, "username": "approved_super"},
        {"id": 71, "username": "approved_viewer"},
        {"id": 70, "username": "rino"},
    ]
    assert len({candidate["id"] for candidate in candidates}) == 3


def test_unapproved_rino_can_be_assigned_but_other_unapproved_users_cannot(renewal_db):
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 80, "rino", {}, approved=False)
    _seed_user(conn, 81, "actor", {"renewal_center_manager": True})
    _seed_user(conn, 82, "unapproved_viewer", {"renewal_center_view": True}, approved=False)
    _seed_user(conn, 83, "unapproved_super", {"super_admin": True}, approved=False)
    _seed_member(conn, 80, (today + timedelta(days=5)).isoformat())
    _seed_member(conn, 82, (today + timedelta(days=5)).isoformat())
    _seed_member(conn, 83, (today + timedelta(days=5)).isoformat())

    result = assign_renewal_case(
        actor_user_id=81, member_id=80, expected_version=0, owner_user_id=80
    )
    assert result["changed"] is True
    assert result["case"]["owner_user_id"] == 80
    assert result["case"]["operational_status"] == "OPEN"
    assert result["case"]["version"] == 2

    for member_id, owner_id in ((82, 82), (83, 83)):
        with pytest.raises(RenewalAssignmentError) as exc_info:
            assign_renewal_case(
                actor_user_id=81,
                member_id=member_id,
                expected_version=0,
                owner_user_id=owner_id,
            )
        assert exc_info.value.code == "invalid_assignee"

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM renewal_cases WHERE member_id IN (82, 83)")
        assert cur.fetchone()[0] == 0
        cur.execute(
            "SELECT COUNT(*) FROM renewal_assignment_events WHERE renewal_case_id IN "
            "(SELECT id FROM renewal_cases WHERE member_id IN (82, 83))"
        )
        assert cur.fetchone()[0] == 0


@pytest.mark.parametrize(
    "member_id,end_date,expected_code",
    [
        (20, None, "member_not_found"),
        (21, "15/09/2026", "ineligible_member"),
        (22, "2026-07-01", "ineligible_member"),
    ],
)
def test_member_must_be_current_and_eligible(renewal_db, member_id, end_date, expected_code):
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 20, "eligible_owner", {"renewal_center_view": True})
    if end_date is not None:
        _seed_member(conn, member_id, end_date)

    with pytest.raises(RenewalAssignmentError) as exc_info:
        assign_renewal_case(
            actor_user_id=20,
            member_id=member_id,
            expected_version=0,
            owner_user_id=20,
        )
    assert exc_info.value.code == expected_code
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM renewal_cases")
        assert cur.fetchone()[0] == 0
        cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
        assert cur.fetchone()[0] == 0


def test_assignment_event_failure_rolls_back_case_and_assignment(renewal_db):
    import psycopg2
    from psycopg2 import sql
    from system_app.renewal.queries import assign_renewal_case

    conn, today, schema = renewal_db
    _seed_user(conn, 30, "actor", {"renewal_center_manager": True})
    _seed_user(conn, 31, "owner", {"renewal_center_view": True})
    _seed_member(conn, 30, (today + timedelta(days=4)).isoformat())
    trigger_name = "renewal_phase1b2_fail_event_trigger"
    function_name = "renewal_phase1b2_fail_event"
    try:
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL(
                    "CREATE OR REPLACE FUNCTION {}() RETURNS trigger "
                    "LANGUAGE plpgsql AS $$ BEGIN "
                    "RAISE EXCEPTION 'test-only assignment event failure'; "
                    "END; $$"
                ).format(sql.Identifier(function_name))
            )
            cur.execute(
                sql.SQL(
                    "CREATE TRIGGER {} BEFORE INSERT ON renewal_assignment_events "
                    "FOR EACH ROW EXECUTE FUNCTION {}()"
                ).format(sql.Identifier(trigger_name), sql.Identifier(function_name))
            )
        conn.commit()

        with pytest.raises(psycopg2.Error, match="test-only assignment event failure"):
            assign_renewal_case(
                actor_user_id=30,
                member_id=30,
                expected_version=0,
                owner_user_id=31,
            )
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM renewal_cases")
            assert cur.fetchone()[0] == 0
            cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
            assert cur.fetchone()[0] == 0
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(
                sql.SQL("DROP TRIGGER IF EXISTS {} ON renewal_assignment_events").format(
                    sql.Identifier(trigger_name)
                )
            )
            cur.execute(
                sql.SQL("DROP FUNCTION IF EXISTS {}()").format(sql.Identifier(function_name))
            )
        conn.commit()
        assert re.fullmatch(SCHEMA_PATTERN, schema)


def test_reassignment_increments_once_and_preserves_waiting_and_paused(renewal_db):
    from system_app.renewal.queries import assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 40, "actor", {"renewal_center_manager": True})
    _seed_user(conn, 41, "first_owner", {"renewal_center_view": True})
    _seed_user(conn, 42, "second_owner", {"renewal_center_view": True})
    _seed_member(conn, 40, (today + timedelta(days=3)).isoformat())
    initial = assign_renewal_case(actor_user_id=40, member_id=40, expected_version=0, owner_user_id=41)

    for status, expected_version in (("WAITING", 2), ("PAUSED", 3)):
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE renewal_cases SET operational_status = %s WHERE member_id = 40",
                (status,),
            )
        conn.commit()
        result = assign_renewal_case(
            actor_user_id=40,
            member_id=40,
            expected_version=expected_version,
            owner_user_id=42 if status == "WAITING" else 41,
        )
        assert result["case"]["operational_status"] == status

    with conn.cursor() as cur:
        cur.execute(
            "SELECT previous_owner_user_id, new_owner_user_id, changed_by_user_id "
            "FROM renewal_assignment_events WHERE renewal_case_id = %s "
            "ORDER BY id",
            (initial["case"]["id"],),
        )
        events = cur.fetchall()
    assert [(row[0], row[1], row[2]) for row in events] == [(None, 41, 40), (41, 42, 40), (42, 41, 40)]


def test_same_owner_initial_replay_and_stale_conflict_preserve_state(renewal_db):
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, _schema = renewal_db
    _seed_user(conn, 50, "owner", {"renewal_center_view": True})
    _seed_user(conn, 51, "other", {"renewal_center_view": True})
    _seed_member(conn, 50, (today + timedelta(days=2)).isoformat())
    first = assign_renewal_case(actor_user_id=50, member_id=50, expected_version=0, owner_user_id=50)
    replay = assign_renewal_case(actor_user_id=50, member_id=50, expected_version=0, owner_user_id=50)
    assert replay["changed"] is False
    with pytest.raises(RenewalAssignmentError) as exc_info:
        assign_renewal_case(actor_user_id=50, member_id=50, expected_version=0, owner_user_id=51)
    assert exc_info.value.code == "assignment_conflict"
    with conn.cursor() as cur:
        cur.execute("SELECT owner_user_id, version FROM renewal_cases WHERE id = %s", (first["case"]["id"],))
        assert cur.fetchone() == (50, 2)
        cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
        assert cur.fetchone()[0] == 1


def test_concurrent_first_assignment_is_bounded_and_unique(renewal_db, monkeypatch):
    import psycopg2
    from psycopg2 import sql
    from system_app.renewal import transactions
    from system_app.renewal.queries import RenewalAssignmentError, assign_renewal_case

    conn, today, schema = renewal_db
    _seed_user(conn, 60, "actor_one", {"renewal_center_manager": True})
    _seed_user(conn, 61, "owner_one", {"renewal_center_view": True})
    _seed_user(conn, 62, "owner_two", {"renewal_center_view": True})
    _seed_member(conn, 60, (today + timedelta(days=5)).isoformat())
    connections = []
    for _ in range(2):
        other = psycopg2.connect(TEST_DATABASE_URL)
        other.autocommit = False
        with other.cursor() as cur:
            cur.execute(sql.SQL("SET search_path TO {}, public").format(sql.Identifier(schema)))
        other.commit()
        connections.append(other)

    class TwoConnectionPool:
        def __init__(self, values):
            self.values = list(values)
            self.lock = threading.Lock()

        def getconn(self):
            with self.lock:
                return self.values.pop()

        def putconn(self, returned, close=False):
            with self.lock:
                if not close:
                    self.values.append(returned)

    concurrent_pool = TwoConnectionPool(connections)
    monkeypatch.setattr(transactions, "get_connection_pool", lambda: concurrent_pool)
    results = []
    errors = []

    def attempt(owner):
        try:
            results.append(assign_renewal_case(actor_user_id=60, member_id=60, expected_version=0, owner_user_id=owner))
        except RenewalAssignmentError as exc:
            errors.append(exc)

    threads = [threading.Thread(target=attempt, args=(owner,)) for owner in (61, 62)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    try:
        assert all(not thread.is_alive() for thread in threads), "concurrent assignment test timed out"
        assert len(results) == 1
        assert len(errors) == 1
        assert errors[0].code == "assignment_conflict"
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM renewal_cases WHERE member_id = 60")
            assert cur.fetchone()[0] == 1
            cur.execute("SELECT COUNT(*) FROM renewal_assignment_events")
            assert cur.fetchone()[0] == 1
    finally:
        for other in connections:
            if not other.closed:
                other.close()
