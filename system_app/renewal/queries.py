"""Read-only queries for the Renewal Command Center Phase 1A."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from system_app.func import get_cairo_date
from system_app.queries import query_db

RENEWAL_FILTERS = {"all", "upcoming", "due_soon", "urgent", "expired"}


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
        {_base_cte()}
        SELECT COUNT(*) AS count
        FROM eligible_members
        WHERE {where_clause}
    """
    count_args = _base_params(business_date) + where_args
    count_row = query_db(count_query, tuple(count_args), one=True) or {}
    total_count = int(count_row.get("count") or 0)

    query = f"""
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
        ORDER BY membership_end_date ASC, id ASC
        LIMIT %s OFFSET %s
    """
    offset = (safe_page - 1) * safe_per_page
    args = _base_params(business_date) + where_args + [safe_per_page, offset]
    rows = query_db(query, tuple(args)) or []
    return [dict(row) for row in rows], total_count
