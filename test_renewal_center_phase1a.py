from datetime import date
from pathlib import Path

import pytest

from system_app.renewal.queries import classify_renewal_urgency, get_renewal_queue


def test_renewal_urgency_boundaries_are_cairo_date_based():
    today = date(2026, 9, 17)
    cases = [
        (31, None),
        (30, "UPCOMING"),
        (15, "UPCOMING"),
        (14, "DUE_SOON"),
        (8, "DUE_SOON"),
        (7, "URGENT"),
        (0, "URGENT"),
        (-1, "EXPIRED"),
        (-30, "EXPIRED"),
        (-31, None),
    ]

    for offset, expected in cases:
        end_date = today.fromordinal(today.toordinal() + offset)
        assert classify_renewal_urgency(end_date, today) == expected


def test_invalid_or_ambiguous_end_dates_are_not_eligible():
    today = date(2026, 9, 17)
    assert classify_renewal_urgency("not-a-date", today) is None
    assert classify_renewal_urgency("17/09/2026", today) is None
    assert classify_renewal_urgency("", today) is None


def test_queue_query_is_member_only_parameterized_and_deterministically_ordered(monkeypatch):
    calls = []

    def fake_query_db(query, params=(), one=False):
        calls.append((query, params, one))
        if one:
            return {"count": 2}
        return [
            {
                "id": 7,
                "name": "Same Name",
                "membership_packages": "1 Month",
                "end_date": "2026-09-20",
                "membership_status": "VAL",
                "membership_end_date": date(2026, 9, 20),
                "days_remaining": 3,
                "urgency": "URGENT",
            },
            {
                "id": 9,
                "name": "Same Name",
                "membership_packages": "1 Month",
                "end_date": "2026-09-20",
                "membership_status": "VAL",
                "membership_end_date": date(2026, 9, 20),
                "days_remaining": 3,
                "urgency": "URGENT",
            },
        ]

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    rows, total = get_renewal_queue(
        today=date(2026, 9, 17),
        queue_filter="urgent",
        search="Same Name",
        page=2,
        per_page=25,
    )

    assert total == 2
    assert [row["id"] for row in rows] == [7, 9]
    assert len(calls) == 2
    for query, params, _one in calls:
        assert query.lstrip().upper().startswith("SELECT")
        assert "FROM members m" in query
        assert "crm_leads" not in query
        assert "phone" not in query.lower()
        assert "%s" in query
        assert "ORDER BY membership_end_date ASC, id ASC" in query or "COUNT(*)" in query
        assert any("Same Name" in str(value) for value in params)


def test_query_db_compatibility_reads_top_level_select_count_and_rows(monkeypatch):
    calls = []
    expected_rows = [_test_member(198, "Eligible")]

    def select_only_query_db(query, params=(), one=False):
        calls.append((query, params, one))
        if not query.lstrip().upper().startswith("SELECT"):
            return None
        return {"count": 198} if one else expected_rows

    monkeypatch.setattr("system_app.renewal.queries.query_db", select_only_query_db)
    rows, total = get_renewal_queue(
        today=date(2026, 9, 17),
        queue_filter="urgent",
        search="198",
        page=3,
        per_page=10,
    )

    assert total == 198
    assert rows == expected_rows
    assert len(calls) == 2
    assert all(query.lstrip().upper().startswith("SELECT") for query, _, _ in calls)
    assert "LOWER(urgency) = %s" in calls[0][0]
    assert "CAST(id AS TEXT) = %s OR name ILIKE %s" in calls[0][0]
    assert "ORDER BY membership_end_date ASC, id ASC" in calls[1][0]
    assert calls[1][1][-2:] == (10, 20)


def test_queue_filter_and_page_are_bounded(monkeypatch):
    observed = []

    def fake_query_db(query, params=(), one=False):
        observed.append((query, params, one))
        return {"count": 0} if one else []

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    rows, total = get_renewal_queue(
        today=date(2026, 9, 17),
        queue_filter="not-a-filter",
        search="1; DROP TABLE members",
        page=-4,
        per_page=1000,
    )

    assert rows == []
    assert total == 0
    assert observed
    assert "DROP TABLE" in observed[0][1][-1]
    assert observed[-1][1][-2:] == (100, 0)


def test_template_is_read_only_and_uses_the_existing_member_route():
    template = Path("system_app/templates/renewal_center.html").read_text(encoding="utf-8")
    assert 'method="get"' in template.lower()
    assert 'url_for(member_url_endpoint, member_id=item.id)' in template
    assert "phone" not in template.lower()
    assert "setinterval" not in template.lower()
    assert "<form" in template
    assert 'type="submit"' in template


def test_renewal_filter_uses_scoped_change_listener_and_manual_search_fallback():
    template = Path("system_app/templates/renewal_center.html").read_text(encoding="utf-8")
    script = Path("system_app/static/js/renewal_center.js").read_text(encoding="utf-8")

    assert "data-renewal-filter-form" in template
    assert "data-renewal-urgency-filter" in template
    assert 'method="get"' in template.lower()
    assert 'type="submit"' in template
    assert "renewal_center.js" in template
    assert "addEventListener('change'" in script
    assert "requestSubmit" in script
    assert "data-renewal-filter-form" in script
    assert "form.addEventListener('submit', function (event)" in script
    assert "event.preventDefault()" in script
    assert "if (typeof form.requestSubmit === 'function')" in script
    assert "submitting = true;\n            form.requestSubmit()" not in script
    assert "submitting = true;\n        form.submit()" in script
    assert "form.requestSubmit();\n            return;" in script
    assert "form.submit();" in script
    assert ">Search</button>" in template
    assert "Apply filters" not in template
    assert "input" not in script
    assert "keyup" not in script
    assert "fetch" not in script
    assert "XMLHttpRequest" not in script
    assert "setInterval" not in script
    assert "setTimeout" not in script
    assert "location.reload" not in script


def _test_member(member_id, name="Member", days_remaining=3):
    return {
        "id": member_id,
        "name": name,
        "membership_packages": "1 Month",
        "end_date": "2026-09-20",
        "membership_status": "VAL",
        "membership_end_date": date(2026, 9, 20),
        "days_remaining": days_remaining,
        "urgency": "URGENT",
    }


@pytest.fixture
def web_app(monkeypatch):
    # Block all psycopg2 connection attempts before importing the full app. This
    # keeps route tests isolated even when env_loader populated a DATABASE_URL.
    import psycopg2

    def blocked_connect(*_args, **_kwargs):
        raise RuntimeError("database access is blocked in Renewal route tests")

    monkeypatch.setattr(psycopg2, "connect", blocked_connect)
    from system_app.app import app
    import jinja2

    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False, RENEWAL_COMMAND_CENTER_ENABLED=True)
    monkeypatch.setattr(app.jinja_env, "undefined", jinja2.ChainableUndefined)
    return app


def _login_as(client, user):
    with client.session_transaction() as session:
        session["user_id"] = user.get("id", 1)


def test_disabled_route_fails_before_permission_or_query(web_app, monkeypatch):
    from system_app import app as app_module

    web_app.config["RENEWAL_COMMAND_CENTER_ENABLED"] = False
    monkeypatch.setattr(app_module, "get_current_user", lambda: {"id": 1, "username": "staff", "permissions": {}})
    monkeypatch.setattr("system_app.renewal.routes.get_renewal_queue", lambda **_: pytest.fail("query must not run"))

    response = web_app.test_client().get("/renewal/")

    assert response.status_code == 404


def test_authorized_route_renders_and_preserves_filter_search(web_app, monkeypatch):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 1,
        "username": "staff",
        "is_approved": True,
        "permissions": {"renewal_center_view": True},
    })
    monkeypatch.setattr(
        "system_app.renewal.routes.get_renewal_queue",
        lambda **kwargs: ([_test_member(4, "Alice")], 1),
    )

    client = web_app.test_client()
    _login_as(client, {"id": 1})
    response = client.get("/renewal/?filter=urgent&search=Alice&page=1")

    assert response.status_code == 200
    assert b"Alice" in response.data
    assert b"Renewal Command Center" in response.data


@pytest.mark.parametrize(
    "user",
    [
        {"id": 2, "username": "staff", "is_approved": True, "permissions": {}},
        {"id": 3, "username": "crm-user", "is_approved": True, "permissions": {"crm_view": True}},
        {"id": 4, "username": "crm-admin", "is_approved": True, "permissions": {"crm_all_leads": True}},
        {"id": 5, "username": "normal", "is_approved": True, "permissions": {}},
    ],
)
def test_renewal_permission_is_not_granted_by_crm_or_username(web_app, monkeypatch, user):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: user)
    client = web_app.test_client()
    _login_as(client, user)

    response = client.get("/renewal/")

    assert response.status_code == 302


def test_existing_generic_super_admin_mechanism_allows_access(web_app, monkeypatch):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 6,
        "username": "rino",
        "is_approved": True,
        "permissions": {},
    })
    monkeypatch.setattr(
        "system_app.renewal.routes.get_renewal_queue",
        lambda **kwargs: ([], 0),
    )
    client = web_app.test_client()
    _login_as(client, {"id": 6})

    assert client.get("/renewal/").status_code == 200


def test_navigation_visibility_uses_flag_and_explicit_permission(web_app):
    def render_nav(enabled, permissions):
        web_app.config["RENEWAL_COMMAND_CENTER_ENABLED"] = enabled
        source = Path("system_app/templates/index.html").read_text(encoding="utf-8")
        start = source.index("{% if renewal_center_enabled")
        end = source.index("{% endif %}", start) + len("{% endif %}")
        navigation_block = source[start:end]
        with web_app.test_request_context("/"):
            return web_app.jinja_env.from_string(navigation_block).render(
                user_permissions=permissions,
                renewal_center_enabled=enabled,
            )

    assert "Renewal Command Center" not in render_nav(False, {"renewal_center_view": True})
    assert "Renewal Command Center" not in render_nav(True, {})
    assert "Renewal Command Center" in render_nav(True, {"renewal_center_view": True})
    crm_template = Path("system_app/templates/crm_dashboard.html").read_text(encoding="utf-8")
    assert "renewal.renewal_center" not in crm_template


def test_super_admin_navigation_uses_existing_generic_context(web_app):
    source = Path("system_app/templates/index.html").read_text(encoding="utf-8")
    start = source.index("{% if renewal_center_enabled")
    end = source.index("{% endif %}", start) + len("{% endif %}")
    with web_app.test_request_context("/"):
        rendered = web_app.jinja_env.from_string(source[start:end]).render(
            user_permissions={"super_admin": True}, renewal_center_enabled=True
        )
    assert "Renewal Command Center" in rendered


def test_out_of_range_page_requeries_last_valid_page(web_app, monkeypatch):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 1,
        "username": "staff",
        "is_approved": True,
        "permissions": {"renewal_center_view": True},
    })
    calls = []

    def fake_queue(**kwargs):
        calls.append(kwargs["page"])
        if kwargs["page"] == 2:
            return ([_test_member(8, "Last Page Member")], 26)
        return ([], 26)

    monkeypatch.setattr("system_app.renewal.routes.get_renewal_queue", fake_queue)
    client = web_app.test_client()
    _login_as(client, {"id": 1})
    response = client.get("/renewal/?page=99&filter=urgent&search=Last")

    assert response.status_code == 200
    assert b"Last Page Member" in response.data
    assert b"Page 2 of 2" in response.data
    assert calls == [99, 2]


@pytest.mark.parametrize("page", ["0", "-3", "not-an-int"])
def test_invalid_page_values_normalize_to_first_page(web_app, monkeypatch, page):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 1,
        "username": "staff",
        "is_approved": True,
        "permissions": {"renewal_center_view": True},
    })
    monkeypatch.setattr(
        "system_app.renewal.routes.get_renewal_queue",
        lambda **kwargs: ([_test_member(1, "First")], 1),
    )
    client = web_app.test_client()
    _login_as(client, {"id": 1})
    response = client.get(f"/renewal/?page={page}")

    assert response.status_code == 200
    assert b"Page 1 of 1" not in response.data  # pagination is hidden for one page
    assert b"First" in response.data


def test_empty_and_single_page_results_are_consistent(web_app, monkeypatch):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 1,
        "username": "staff",
        "is_approved": True,
        "permissions": {"renewal_center_view": True},
    })
    responses = iter([([], 0), ([_test_member(2, "Only Member")], 1)])
    monkeypatch.setattr("system_app.renewal.routes.get_renewal_queue", lambda **_: next(responses))
    client = web_app.test_client()
    _login_as(client, {"id": 1})

    empty = client.get("/renewal/?page=8")
    one = client.get("/renewal/?page=1")
    assert b"Page 1 of 1" not in empty.data
    assert b"No members match" in empty.data
    assert b"Only Member" in one.data


def test_query_failure_is_safe_and_post_is_not_supported(web_app, monkeypatch):
    from system_app import app as app_module

    monkeypatch.setattr(app_module, "get_current_user", lambda: {
        "id": 1,
        "username": "staff",
        "is_approved": True,
        "permissions": {"renewal_center_view": True},
    })
    monkeypatch.setattr("system_app.renewal.routes.get_renewal_queue", lambda **_: (_ for _ in ()).throw(RuntimeError("db detail")))
    client = web_app.test_client()
    _login_as(client, {"id": 1})

    response = client.get("/renewal/")
    post_response = client.post("/renewal/")
    assert response.status_code == 200
    assert b"temporarily unavailable" in response.data
    assert b"db detail" not in response.data
    assert post_response.status_code == 405


def test_queue_identity_is_members_id_and_never_phone_or_crm(monkeypatch):
    rows = [_test_member(10, "Duplicate Name"), _test_member(11, "Duplicate Name")]
    calls = []

    def fake_query_db(query, params=(), one=False):
        calls.append(query)
        return {"count": 2} if one else rows

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    result, total = get_renewal_queue(today=date(2026, 9, 17))

    assert total == 2
    assert [item["id"] for item in result] == [10, 11]
    assert len({item["id"] for item in result}) == 2
    assert all("phone" not in item for item in result)
    assert all("crm_leads" not in query.lower() for query in calls)


def test_rendered_queue_does_not_expose_phone(web_app):
    from flask import render_template

    item = _test_member(12, "No Phone Output")
    item["phone"] = "01012345678"
    with web_app.test_request_context("/renewal/"):
        rendered = render_template(
            "renewal_center.html",
            items=[item], page=1, per_page=25, total_count=1,
            total_pages=1, queue_filter="all", search="",
            error_message=None, member_url_endpoint="edit_member",
        )
    assert "01012345678" not in rendered


def test_current_membership_status_is_display_only_and_date_drives_eligibility(monkeypatch):
    rows = [_test_member(20, "Stale Status")]
    rows[0]["membership_status"] = "EX"

    def fake_query_db(query, params=(), one=False):
        return {"count": 1} if one else rows

    monkeypatch.setattr("system_app.renewal.queries.query_db", fake_query_db)
    result, total = get_renewal_queue(today=date(2026, 9, 17))

    assert total == 1
    assert result[0]["id"] == 20
    assert result[0]["membership_status"] == "EX"
