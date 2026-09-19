"""Read-only queries for the Renewal Command Center Phase 1A."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from system_app.func import get_cairo_date
from system_app.queries import query_db

RENEWAL_FILTERS = {"all", "upcoming", "due_soon", "urgent", "expired"}
RENEWAL_WORKFLOW_STATUS_FILTERS = {"all", "unassigned", "open", "waiting", "paused"}


def _as_date(value: date | datetime | str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value).strip()[:10])


def classify_renewal_urgency(end_date: date | datetime | str, today: date | datetime | str) -> str | None:
    """Return the product urgency bucket for an ISO membership end date."""
    try:
        end = _as_date(end_date)
        business_date = _as_date(today)
    except (TypeError, ValueError):
        return None

    days_remaining = (end - business_date).days
    if 15 <= days_remaining <= 30:
        return "UPCOMING"
    if 8 <= days_remaining <= 14:
        return "DUE_SOON"
    if 0 <= days_remaining <= 7:
        return "URGENT"
    if -30 <= days_remaining <= -1:
        return "EXPIRED"
    return None


def _parsed_end_date_sql() -> str:
    """Parse only the repository's canonical YYYY-MM-DD member date format."""
    return """
        CASE
            WHEN SUBSTRING(TRIM(COALESCE(m.end_date, '')), 1, 10)
                 ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
            THEN CAST(SUBSTRING(TRIM(m.end_date), 1, 10) AS DATE)
            ELSE NULL
        END
    """.strip()


def _base_cte() -> str:
    parsed_end_date = _parsed_end_date_sql()
    return f"""
        WITH parsed_members AS (
            SELECT
                m.id,
                m.name,
                m.membership_packages,
                m.end_date,
                m.membership_status,
                {parsed_end_date} AS membership_end_date
            FROM members m
        ), eligible_members AS (
            SELECT
                id,
                name,
                membership_packages,
                end_date,
                membership_status,
                membership_end_date,
                (membership_end_date - %s::date) AS days_remaining,
                CASE
                    WHEN (membership_end_date - %s::date) BETWEEN 15 AND 30 THEN 'UPCOMING'
                    WHEN (membership_end_date - %s::date) BETWEEN 8 AND 14 THEN 'DUE_SOON'
                    WHEN (membership_end_date - %s::date) BETWEEN 0 AND 7 THEN 'URGENT'
                    WHEN (membership_end_date - %s::date) BETWEEN -30 AND -1 THEN 'EXPIRED'
                    ELSE NULL
                END AS urgency
            FROM parsed_members
            WHERE membership_end_date BETWEEN (%s::date - 30) AND (%s::date + 30)
        )
    """


def _where_clause(queue_filter: str, search: str) -> tuple[str, list[Any]]:
    clauses = ["urgency IS NOT NULL"]
    args: list[Any] = []

    if queue_filter != "all":
        clauses.append("LOWER(urgency) = %s")
        args.append(queue_filter)

    if search:
        clauses.append("(CAST(id AS TEXT) = %s OR name ILIKE %s)")
        args.extend([search if search.isdigit() else "-1", f"%{search}%"])

    return " AND ".join(clauses), args


def _base_params(today: date) -> list[Any]:
    # The date is repeated for the derived days, urgency, and eligibility bounds.
    return [today, today, today, today, today, today, today]


def get_renewal_queue(
    *,
    today: date | None = None,
    queue_filter: str = "all",
    search: str = "",
    page: int = 1,
    per_page: int = 25,
) -> tuple[list[dict[str, Any]], int]:
    """Return one current member row per eligible member and the total count."""
    business_date = today or get_cairo_date()
    normalized_filter = queue_filter if queue_filter in RENEWAL_FILTERS else "all"
    normalized_search = (search or "").strip()
    safe_page = max(int(page or 1), 1)
    safe_per_page = max(min(int(per_page or 25), 100), 1)
    where_clause, where_args = _where_clause(normalized_filter, normalized_search)

    count_query = f"""
        SELECT COUNT(*) AS count
        FROM (
            {_base_cte()}
            SELECT id
            FROM eligible_members
            WHERE {where_clause}
        ) AS renewal_result
    """
    count_args = _base_params(business_date) + where_args
    count_row = query_db(count_query, tuple(count_args), one=True) or {}
    total_count = int(count_row.get("count") or 0)

    query = f"""
        SELECT
            id,
            name,
            membership_packages,
            end_date,
            membership_status,
            membership_end_date,
            days_remaining,
            urgency
        FROM (
            {_base_cte()}
            SELECT
                id,
                name,
                membership_packages,
                end_date,
                membership_status,
                membership_end_date,
                days_remaining,
                urgency
            FROM eligible_members
            WHERE {where_clause}
        ) AS renewal_result
        ORDER BY membership_end_date ASC, id ASC
        LIMIT %s OFFSET %s
    """
    offset = (safe_page - 1) * safe_per_page
    args = _base_params(business_date) + where_args + [safe_per_page, offset]
    rows = query_db(query, tuple(args)) or []
    return [dict(row) for row in rows], total_count


def _workflow_source_sql() -> str:
    """Build the eligible-member/case source without changing Phase 1A SQL."""
    return f"""
        SELECT
            eligible.id,
            eligible.name,
            eligible.membership_packages,
            eligible.end_date,
            eligible.membership_status,
            eligible.membership_end_date,
            eligible.days_remaining,
            eligible.urgency,
            renewal_case.id AS case_id,
            renewal_case.owner_user_id,
            owner.username AS owner_username,
            COALESCE(renewal_case.operational_status, 'UNASSIGNED') AS operational_status,
            COALESCE(renewal_case.version, 0) AS version,
            renewal_case.next_follow_up_at
        FROM (
            {_base_cte()}
            SELECT
                id,
                name,
                membership_packages,
                end_date,
                membership_status,
                membership_end_date,
                days_remaining,
                urgency
            FROM eligible_members
            WHERE urgency IS NOT NULL
        ) AS eligible
        LEFT JOIN renewal_cases AS renewal_case
          ON renewal_case.member_id = eligible.id
         AND renewal_case.cycle_end_date = eligible.membership_end_date
        LEFT JOIN users AS owner
          ON owner.id = renewal_case.owner_user_id
    """


def _workflow_where_clause(
    queue_filter: str,
    status_filter: str,
    owner_filter: str,
    search: str,
    *,
    manager: bool,
    actor_user_id: int | None,
) -> tuple[str, list[Any]]:
    clauses = ["renewal_result.urgency IS NOT NULL"]
    args: list[Any] = []

    if queue_filter != "all":
        clauses.append("LOWER(renewal_result.urgency) = %s")
        args.append(queue_filter)

    if status_filter != "all":
        clauses.append("LOWER(renewal_result.operational_status) = %s")
        args.append(status_filter)

    if manager:
        if owner_filter == "unassigned":
            clauses.append("renewal_result.owner_user_id IS NULL")
        elif owner_filter.isdigit() and int(owner_filter) > 0:
            clauses.append("renewal_result.owner_user_id = %s")
            args.append(int(owner_filter))
    else:
        clauses.append("renewal_result.owner_user_id = %s")
        args.append(actor_user_id)

    if search:
        clauses.append(
            "(CAST(renewal_result.id AS TEXT) = %s "
            "OR renewal_result.name ILIKE %s)"
        )
        args.extend([search if search.isdigit() else "-1", f"%{search}%"])

    return " AND ".join(clauses), args


def get_renewal_workflow_queue(
    *,
    today: date | None = None,
    queue_filter: str = "all",
    status_filter: str = "all",
    owner_filter: str = "all",
    search: str = "",
    page: int = 1,
    per_page: int = 25,
    manager: bool = False,
    actor_user_id: int | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Return eligible rows joined to cases with server-enforced user scope."""
    business_date = today or get_cairo_date()
    normalized_filter = queue_filter if queue_filter in RENEWAL_FILTERS else "all"
    normalized_status = (
        status_filter if status_filter in RENEWAL_WORKFLOW_STATUS_FILTERS else "all"
    )
    normalized_owner = (owner_filter or "all").strip().lower()
    normalized_search = (search or "").strip()
    safe_page = max(int(page or 1), 1)
    safe_per_page = max(min(int(per_page or 25), 100), 1)
    where_clause, where_args = _workflow_where_clause(
        normalized_filter,
        normalized_status,
        normalized_owner,
        normalized_search,
        manager=manager,
        actor_user_id=actor_user_id,
    )
    source_sql = _workflow_source_sql()
    count_query = f"""
        SELECT COUNT(*) AS count
        FROM ({source_sql}) AS renewal_result
        WHERE {where_clause}
    """
    count_args = _base_params(business_date) + where_args
    count_row = query_db(count_query, tuple(count_args), one=True) or {}
    total_count = int(count_row.get("count") or 0)

    query = f"""
        SELECT
            renewal_result.id,
            renewal_result.name,
            renewal_result.membership_packages,
            renewal_result.end_date,
            renewal_result.membership_status,
            renewal_result.membership_end_date,
            renewal_result.days_remaining,
            renewal_result.urgency,
            renewal_result.case_id,
            renewal_result.owner_user_id,
            renewal_result.owner_username,
            renewal_result.operational_status,
            renewal_result.version,
            renewal_result.next_follow_up_at
        FROM ({source_sql}) AS renewal_result
        WHERE {where_clause}
        ORDER BY renewal_result.membership_end_date ASC, renewal_result.id ASC
        LIMIT %s OFFSET %s
    """
    offset = (safe_page - 1) * safe_per_page
    args = _base_params(business_date) + where_args + [safe_per_page, offset]
    rows = query_db(query, tuple(args)) or []
    return [dict(row) for row in rows], total_count


def get_renewal_assignees() -> list[dict[str, Any]]:
    """Return users eligible for Renewal ownership under the app's bypass rules."""
    rows = query_db(
        """
        SELECT id, username
        FROM users
        WHERE username IS NOT NULL
          AND BTRIM(username) <> ''
          AND (
              username = 'rino'
              OR (
                  is_approved = TRUE
                  AND (
                      COALESCE(permissions ->> 'renewal_center_view', 'false') = 'true'
                      OR COALESCE(permissions ->> 'super_admin', 'false') = 'true'
                  )
              )
          )
        ORDER BY username ASC, id ASC
        """
    ) or []
    return [{"id": row["id"], "username": row["username"]} for row in rows]


class RenewalAssignmentError(Exception):
    """Safe, user-facing assignment failure without database details."""

    def __init__(self, code: str, message: str, status_code: int = 409):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def _permissions_from_row(raw_permissions: Any) -> dict[str, Any]:
    if isinstance(raw_permissions, dict):
        return raw_permissions
    if isinstance(raw_permissions, str):
        import json

        try:
            parsed = json.loads(raw_permissions)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _has_permission(user: dict[str, Any], permission_key: str) -> bool:
    permissions = _permissions_from_row(user.get("permissions"))
    return bool(
        user.get("username") == "rino"
        or permissions.get("super_admin")
        or permissions.get(permission_key)
    )


def _is_eligible_renewal_assignee(user: dict[str, Any]) -> bool:
    """Keep candidate lookup and transactional owner validation consistent."""
    return bool(
        user.get("username") == "rino"
        or (
            user.get("is_approved")
            and _has_permission(user, "renewal_center_view")
        )
    )


def assign_renewal_case(
    *,
    actor_user_id: int,
    member_id: int,
    expected_version: int,
    owner_user_id: int,
) -> dict[str, Any]:
    """Create/assign one current eligible cycle in one transaction."""
    if expected_version < 0:
        raise RenewalAssignmentError("validation_error", "Invalid case version.", 400)

    from system_app.renewal.transactions import run_renewal_transaction

    def operation(cur):
        cur.execute(
            """
            SELECT id, end_date, membership_status
            FROM members
            WHERE id = %s
            FOR UPDATE
            """,
            (member_id,),
        )
        member = cur.fetchone()
        if not member:
            raise RenewalAssignmentError("member_not_found", "Member not found.", 404)

        business_date = get_cairo_date()
        try:
            cycle_end_date = _as_date(member["end_date"])
        except (TypeError, ValueError):
            raise RenewalAssignmentError(
                "ineligible_member",
                "This member is outside the current renewal window.",
                409,
            )
        if classify_renewal_urgency(cycle_end_date, business_date) is None:
            raise RenewalAssignmentError(
                "ineligible_member",
                "This member is outside the current renewal window.",
                409,
            )

        cur.execute(
            """
            SELECT id, username, is_approved, permissions
            FROM users
            WHERE id = %s
            FOR SHARE
            """,
            (owner_user_id,),
        )
        assignee = cur.fetchone()
        if not assignee or not _is_eligible_renewal_assignee(dict(assignee)):
            raise RenewalAssignmentError(
                "invalid_assignee",
                "The selected Renewal owner is not eligible.",
                422,
            )

        created = False
        if expected_version == 0:
            cur.execute(
                """
                INSERT INTO renewal_cases (member_id, cycle_end_date)
                VALUES (%s, %s)
                ON CONFLICT (member_id, cycle_end_date) DO NOTHING
                RETURNING id
                """,
                (member_id, cycle_end_date),
            )
            created = cur.fetchone() is not None

        cur.execute(
            """
            SELECT id, member_id, cycle_end_date, owner_user_id,
                   operational_status, version, next_follow_up_at
            FROM renewal_cases
            WHERE member_id = %s AND cycle_end_date = %s
            FOR UPDATE
            """,
            (member_id, cycle_end_date),
        )
        case = cur.fetchone()
        if not case:
            raise RenewalAssignmentError("assignment_conflict", "The case changed. Refresh and try again.")

        if expected_version == 0 and not created:
            if case["owner_user_id"] == owner_user_id:
                return {"case": dict(case), "changed": False, "created": False}
            raise RenewalAssignmentError("assignment_conflict", "The case was assigned by another user.")

        if expected_version > 0 and case["version"] != expected_version:
            raise RenewalAssignmentError("assignment_conflict", "The case changed. Refresh and try again.")

        if case["owner_user_id"] == owner_user_id:
            return {"case": dict(case), "changed": False, "created": created}

        next_status = "OPEN" if case["operational_status"] == "UNASSIGNED" else case["operational_status"]
        cur.execute(
            """
            UPDATE renewal_cases
            SET owner_user_id = %s,
                operational_status = %s,
                version = version + 1,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s AND version = %s
            """,
            (owner_user_id, next_status, case["id"], case["version"]),
        )
        if cur.rowcount != 1:
            raise RenewalAssignmentError("assignment_conflict", "The case changed. Refresh and try again.")

        cur.execute(
            """
            INSERT INTO renewal_assignment_events
                (renewal_case_id, previous_owner_user_id, new_owner_user_id, changed_by_user_id)
            VALUES (%s, %s, %s, %s)
            """,
            (case["id"], case["owner_user_id"], owner_user_id, actor_user_id),
        )
        cur.execute(
            """
            SELECT id, member_id, cycle_end_date, owner_user_id,
                   operational_status, version, next_follow_up_at
            FROM renewal_cases
            WHERE id = %s
            """,
            (case["id"],),
        )
        return {"case": dict(cur.fetchone()), "changed": True, "created": created}

    return run_renewal_transaction(operation)
