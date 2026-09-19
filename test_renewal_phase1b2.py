from datetime import date
from pathlib import Path

import pytest

from system_app.renewal.queries import get_renewal_workflow_queue


ROOT = Path(__file__).parent


@pytest.fixture
def web_app(monkeypatch):
    import psycopg2

    monkeypatch.setattr(
        psycopg2,
        "connect",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("database access is blocked in Renewal workflow tests")
        ),
    )
    from system_app.app import app

    app.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RENEWAL_COMMAND_CENTER_ENABLED=True,
        RENEWAL_WORKFLOW_ENABLED=True,
    )
    return app


def _login(client, user_id=1):
    with client.session_transaction() as session:
        session["user_id"] = user_id


def _user(username="manager", permissions=None):
    return {
        "id": 1,
        "username": username,
        "is_approved": True,
        "permissions": permissions or {},
    }


def test_workflow_queue_enforces_employee_scope_and_manager_owner_filter(monkeypatch):
    calls = []

    def fake_query_db(query, params=(), one=False):
        calls.append((query, params, one))
        return {"count": 1} if one else [{"id": 4, "owner_user_id": 7}]

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)

    rows, total = get_renewal_workflow_queue(
        actor_user_id=7,
        manager=False,
        owner_filter="999",
        page=1,
    )
    assert total == 1
    assert rows[0]["id"] == 4
    assert "renewal_result.owner_user_id = %s" in calls[0][0]
    assert 7 in calls[0][1]
    assert "999" not in [str(value) for value in calls[0][1]]

    calls.clear()
    get_renewal_workflow_queue(
        actor_user_id=7,
        manager=True,
        owner_filter="unassigned",
        status_filter="open",
    )
    assert "renewal_result.owner_user_id IS NULL" in calls[0][0]
    assert "LOWER(renewal_result.operational_status) = %s" in calls[0][0]


def test_renewal_assignee_policy_allows_only_rino_bypass_or_approved_permissioned_users():
    from system_app.renewal.queries import _is_eligible_renewal_assignee

    assert _is_eligible_renewal_assignee({"username": "rino", "is_approved": False, "permissions": {}})
    assert _is_eligible_renewal_assignee({"username": "viewer", "is_approved": True, "permissions": {"renewal_center_view": True}})
    assert _is_eligible_renewal_assignee({"username": "admin", "is_approved": True, "permissions": {"super_admin": True}})
    assert not _is_eligible_renewal_assignee({"username": "viewer", "is_approved": False, "permissions": {"renewal_center_view": True}})
    assert not _is_eligible_renewal_assignee({"username": "admin", "is_approved": False, "permissions": {"super_admin": True}})
    assert not _is_eligible_renewal_assignee({"username": "plain", "is_approved": True, "permissions": {}})


def test_assignment_requires_both_manager_and_assign_permissions(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(permissions={"renewal_center_view": True, "renewal_center_assign": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    client = web_app.test_client()
    _login(client)

    response = client.post(
        "/renewal/cases/assign",
        data={"member_id": "4", "owner_user_id": "8", "expected_version": "0"},
    )
    assert response.status_code == 403


def test_assignment_route_is_disabled_before_permission_or_write(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    web_app.config["RENEWAL_WORKFLOW_ENABLED"] = False
    user = _user(permissions={"renewal_center_view": True, "renewal_center_manager": True, "renewal_center_assign": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "assign_renewal_case",
        lambda **_: pytest.fail("disabled workflow must not write"),
    )
    client = web_app.test_client()
    _login(client)

    assert client.post("/renewal/cases/assign", data={}).status_code == 404


def test_manager_assignment_uses_authenticated_actor_and_preserves_safe_filters(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(
        permissions={
            "renewal_center_view": True,
            "renewal_center_manager": True,
            "renewal_center_assign": True,
        }
    )
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    captured = {}

    def fake_assign(**kwargs):
        captured.update(kwargs)
        return {"changed": True, "created": True, "case": {"id": 9}}

    monkeypatch.setattr(renewal_routes, "assign_renewal_case", fake_assign)
    client = web_app.test_client()
    _login(client)
    response = client.post(
        "/renewal/cases/assign?filter=urgent&status=unassigned&owner=all&search=Alice&page=2",
        data={"member_id": "4", "owner_user_id": "8", "expected_version": "0"},
    )

    assert response.status_code == 302
    assert captured == {
        "actor_user_id": 1,
        "member_id": 4,
        "owner_user_id": 8,
        "expected_version": 0,
    }
    assert "filter=urgent" in response.location
    assert "search=Alice" in response.location
    assert "page=2" in response.location


def test_manager_page_renders_workflow_owner_controls(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(
        permissions={
            "renewal_center_view": True,
            "renewal_center_manager": True,
            "renewal_center_assign": True,
        }
    )
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_workflow_queue",
        lambda **_: ([
            {
                "id": 4,
                "name": "Alice",
                "days_remaining": 3,
                "urgency": "URGENT",
                "membership_end_date": "2026-09-20",
                "membership_packages": "1 Month",
                "membership_status": "ACTIVE",
                "case_id": None,
                "owner_user_id": None,
                "owner_username": None,
                "operational_status": "UNASSIGNED",
                "version": 0,
            }
        ], 1),
    )
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_assignees",
        lambda: [{"id": 2, "username": "owner"}],
    )
    client = web_app.test_client()
    _login(client)

    response = client.get("/renewal/?status=unassigned")
    assert response.status_code == 200
    assert b"Workflow status" in response.data
    assert b"Assign Renewal owner" in response.data
    assert b"owner" in response.data


def test_manager_without_assign_sees_owner_filter_but_no_assignment_form(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(permissions={"renewal_center_view": True, "renewal_center_manager": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_workflow_queue",
        lambda **kwargs: ([], 0) if kwargs["manager"] else pytest.fail("manager scope expected"),
    )
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_assignees",
        lambda: [{"id": 2, "username": "approved-owner"}],
    )
    client = web_app.test_client()
    _login(client)

    response = client.get("/renewal/?owner=2")
    assert response.status_code == 200
    assert b"Owner" in response.data
    assert b"approved-owner" in response.data
    assert b"Assign Renewal owner" not in response.data
    assert b"renewal.assign_case" not in response.data

    assert client.post(
        "/renewal/cases/assign",
        data={"member_id": "4", "owner_user_id": "2", "expected_version": "0"},
    ).status_code == 403


def test_employee_scope_ignores_owner_parameter_and_hides_manager_controls(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(permissions={"renewal_center_view": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    observed = {}

    def fake_queue(**kwargs):
        observed.update(kwargs)
        return ([], 0)

    monkeypatch.setattr(renewal_routes, "get_renewal_workflow_queue", fake_queue)
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_assignees",
        lambda: pytest.fail("employee must not load manager assignees"),
    )
    client = web_app.test_client()
    _login(client)

    response = client.get("/renewal/?owner=999&status=waiting")
    assert response.status_code == 200
    assert observed["manager"] is False
    assert observed["actor_user_id"] == 1
    assert observed["owner_filter"] == "all"
    assert b"Owner" not in response.data
    assert b"Assign Renewal owner" not in response.data


def test_disabled_workflow_does_not_load_workflow_query_or_assignees(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    web_app.config["RENEWAL_WORKFLOW_ENABLED"] = False
    user = _user(permissions={"renewal_center_view": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_queue",
        lambda **_: ([], 0),
    )
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_workflow_queue",
        lambda **_: pytest.fail("workflow query must not run"),
    )
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_assignees",
        lambda: pytest.fail("assignees must not load"),
    )
    client = web_app.test_client()
    _login(client)

    response = client.get("/renewal/")
    assert response.status_code == 200
    assert b"Workflow status" not in response.data
    assert b"Owner" not in response.data


def test_assignment_errors_are_safe_and_invalid_input_does_not_write(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    user = _user(permissions={"renewal_center_view": True, "renewal_center_manager": True, "renewal_center_assign": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(renewal_routes, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "assign_renewal_case",
        lambda **_: pytest.fail("invalid form must not call assignment service"),
    )
    monkeypatch.setattr(renewal_routes, "get_renewal_workflow_queue", lambda **_: ([], 0))
    monkeypatch.setattr(renewal_routes, "get_renewal_assignees", lambda: [])
    client = web_app.test_client()
    _login(client)

    invalid = client.post(
        "/renewal/cases/assign",
        data={"member_id": "not-an-id", "owner_user_id": "2", "expected_version": "0"},
    )
    assert invalid.status_code == 302
    with client.session_transaction() as session:
        assert "Invalid Renewal assignment request." in str(session.get("_flashes"))

    monkeypatch.setattr(
        renewal_routes,
        "assign_renewal_case",
        lambda **_: (_ for _ in ()).throw(RuntimeError("secret database details")),
    )
    safe = client.post("/renewal/cases/assign", data={"member_id": "4", "owner_user_id": "2", "expected_version": "0"})
    assert safe.status_code == 302
    with client.session_transaction() as session:
        assert "Renewal assignment is temporarily unavailable. Please try again." in str(session.get("_flashes"))
        assert "secret database details" not in str(session.get("_flashes"))

    monkeypatch.setattr(
        renewal_routes,
        "assign_renewal_case",
        lambda **_: (_ for _ in ()).throw(
            renewal_routes.RenewalAssignmentError("assignment_conflict", "Refresh and try again.")
        ),
    )
    controlled = client.post("/renewal/cases/assign", data={"member_id": "4", "owner_user_id": "2", "expected_version": "0"})
    assert controlled.status_code == 302
    with client.session_transaction() as session:
        assert "Refresh and try again." in str(session.get("_flashes"))
        assert "assignment_conflict" not in str(session.get("_flashes"))


def test_phase1a_path_remains_unchanged_when_workflow_disabled(web_app, monkeypatch):
    from system_app import app as app_module
    import system_app.renewal.routes as renewal_routes

    web_app.config["RENEWAL_WORKFLOW_ENABLED"] = False
    user = _user(permissions={"renewal_center_view": True})
    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_queue",
        lambda **_: ([
            {
                "id": 4,
                "name": "Phase 1A",
                "days_remaining": 3,
                "urgency": "URGENT",
                "membership_end_date": "2026-09-20",
                "membership_packages": "1 Month",
                "membership_status": "ACTIVE",
            }
        ], 1),
    )
    monkeypatch.setattr(
        renewal_routes,
        "get_renewal_workflow_queue",
        lambda **_: pytest.fail("workflow query must not run when disabled"),
    )
    client = web_app.test_client()
    _login(client)

    response = client.get("/renewal/")
    assert response.status_code == 200
    assert b"Phase 1A" in response.data
    assert b"Assign Renewal owner" not in response.data


def test_workflow_template_contains_only_guarded_assignment_ui():
    template = (ROOT / "system_app/templates/renewal_center.html").read_text(encoding="utf-8")
    assert "RENEWAL_WORKFLOW_ENABLED" not in template
    assert "renewal.assign_case" in template
    assert "method=\"post\"" in template.lower()
    assert "csrf_token()" in template


def test_workflow_template_uses_wide_desktop_layout_and_compact_responsive_controls():
    template = (ROOT / "system_app/templates/renewal_center.html").read_text(encoding="utf-8")
    assert 'class="page{% if workflow_enabled %} workflow-page{% endif %}"' in template
    assert ".page.workflow-page { width: min(1680px, 100%); }" in template
    assert "@media (min-width: 760px)" in template
    assert "@media (min-width: 1400px)" in template
    assert ".page:not(.workflow-page) .table-wrap" in template
    assert ".workflow-page .table-wrap" in template
    assert "@media (min-width: 1100px)" not in template
    assert "workflow-page .cards" in template
    assert "class=\"member-cell\"" in template
    assert "class=\"nowrap-cell\"" in template
    assert "class=\"workflow-badge\"" in template
    assert "class=\"owner-badge\"" in template
    assert "class=\"action-cell\"" in template
    assert ".workflow-page .table-wrap { overflow: visible; }" in template
    assert "min-height: 44px" in template


def test_phase1a_and_manager_workflow_have_equivalent_eligible_ids(monkeypatch):
    from system_app.renewal.queries import get_renewal_queue, get_renewal_workflow_queue

    phase1a_rows = [
        {
            "id": member_id,
            "name": "Same Name",
            "membership_packages": "1 Month",
            "end_date": "2026-09-20",
            "membership_status": "ACTIVE",
            "membership_end_date": date(2026, 9, 20),
            "days_remaining": 3,
            "urgency": "URGENT",
        }
        for member_id in (7, 9)
    ]
    workflow_rows = [dict(row, case_id=None, owner_user_id=None, owner_username=None,
                          operational_status="UNASSIGNED", version=0, next_follow_up_at=None)
                     for row in phase1a_rows]
    calls = []

    def fake_query_db(query, params=(), one=False):
        calls.append(query)
        if one:
            return {"count": 2}
        return workflow_rows if "renewal_cases" in query else phase1a_rows

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    rows_a, count_a = get_renewal_queue(today=date(2026, 9, 17), page=1, per_page=25)
    rows_w, count_w = get_renewal_workflow_queue(
        today=date(2026, 9, 17), page=1, per_page=25, manager=True
    )

    assert count_a == count_w == 2
    assert [row["id"] for row in rows_a] == [row["id"] for row in rows_w] == [7, 9]
    assert all(row["operational_status"] == "UNASSIGNED" for row in rows_w)
    workflow_sql = "\n".join(calls[2:])
    assert "LEFT JOIN renewal_cases" in workflow_sql
    assert "renewal_case.cycle_end_date = eligible.membership_end_date" in workflow_sql
    assert "ORDER BY renewal_result.membership_end_date ASC, renewal_result.id ASC" in workflow_sql


def test_workflow_join_is_current_cycle_only_and_does_not_duplicate_members(monkeypatch):
    from system_app.renewal.queries import get_renewal_workflow_queue

    calls = []

    def fake_query_db(query, params=(), one=False):
        calls.append((query, params, one))
        if one:
            return {"count": 1}
        return [{"id": 7, "operational_status": "UNASSIGNED", "owner_user_id": None}]

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    rows, total = get_renewal_workflow_queue(today=date(2026, 9, 17), manager=True)
    assert total == 1
    assert [row["id"] for row in rows] == [7]
    assert "LEFT JOIN renewal_cases" in calls[0][0]
    assert "renewal_case.member_id = eligible.id" in calls[0][0]
    assert "renewal_case.cycle_end_date = eligible.membership_end_date" in calls[0][0]
    assert "INNER JOIN renewal_cases" not in calls[0][0]


def test_renewal_transaction_returns_healthy_pooled_connection_once(monkeypatch):
    import system_app.renewal.transactions as transactions

    class Cursor:
        def close(self):
            self.closed = True

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()
            self.commits = 0
            self.rollbacks = 0

        def cursor(self, **_kwargs):
            return self.cursor_obj

        def commit(self):
            self.commits += 1

        def rollback(self):
            self.rollbacks += 1

    class Pool:
        def __init__(self, conn):
            self.conn = conn
            self.puts = []

        def getconn(self):
            return self.conn

        def putconn(self, conn, close=False):
            self.puts.append((conn, close))

    conn = Connection()
    pool = Pool(conn)
    monkeypatch.setattr(transactions, "get_connection_pool", lambda: pool)

    assert transactions.run_renewal_transaction(lambda _cur: "ok") == "ok"
    assert conn.commits == 1
    assert conn.rollbacks == 0
    assert pool.puts == [(conn, False)]
    assert conn.cursor_obj.closed is True


def test_renewal_transaction_discards_broken_pooled_connection(monkeypatch):
    import psycopg2
    import system_app.renewal.transactions as transactions

    class Cursor:
        def close(self):
            pass

    class Connection:
        def __init__(self):
            self.rollbacks = 0

        def cursor(self, **_kwargs):
            return Cursor()

        def commit(self):
            raise psycopg2.OperationalError("broken connection")

        def rollback(self):
            self.rollbacks += 1

    class Pool:
        def __init__(self, conn):
            self.conn = conn
            self.puts = []

        def getconn(self):
            return self.conn

        def putconn(self, conn, close=False):
            self.puts.append((conn, close))

    conn = Connection()
    pool = Pool(conn)
    monkeypatch.setattr(transactions, "get_connection_pool", lambda: pool)

    with pytest.raises(psycopg2.OperationalError, match="broken connection"):
        transactions.run_renewal_transaction(lambda _cur: None)
    assert conn.rollbacks == 1
    assert pool.puts == [(conn, True)]


def test_renewal_transaction_closes_direct_connection_and_preserves_callback_error(monkeypatch):
    import system_app.renewal.transactions as transactions

    class Cursor:
        def close(self):
            self.closed = True

    class Connection:
        def __init__(self):
            self.cursor_obj = Cursor()
            self.rollbacks = 0
            self.closed = 0

        def cursor(self, **_kwargs):
            return self.cursor_obj

        def commit(self):
            raise AssertionError("commit must not run after callback failure")

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closed += 1

    conn = Connection()
    monkeypatch.setattr(transactions, "get_connection_pool", lambda: None)
    monkeypatch.setattr(transactions, "get_database_url", lambda: "isolated-test-url")
    monkeypatch.setattr(transactions.psycopg2, "connect", lambda _url: conn)

    with pytest.raises(ValueError, match="callback failure"):
        transactions.run_renewal_transaction(
            lambda _cur: (_ for _ in ()).throw(ValueError("callback failure"))
        )
    assert conn.rollbacks == 1
    assert conn.closed == 1
    assert conn.cursor_obj.closed is True
