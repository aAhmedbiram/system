"""Data access helpers for the Private Training domain."""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable

import psycopg2
from psycopg2.extras import RealDictCursor

from system_app.func import get_cairo_date
from system_app.queries import get_database_url, query_db

PRIVATE_TRAINING_SUBSCRIPTION_STATUSES = ("ASSIGNED", "ACTIVE", "COMPLETED", "EXPIRED", "CANCELLED")
PRIVATE_TRAINING_SESSION_STATUSES = ("PENDING_MEMBER_APPROVAL", "APPROVED", "REJECTED")

CAIRO_TODAY_SQL = "(CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Cairo')::DATE"


def ensure_private_training_tables() -> None:
    """Create the private-training schema and supporting indexes if needed."""
    db_url = get_database_url()
    conn = psycopg2.connect(db_url)
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS private_training_subscriptions (
                id SERIAL PRIMARY KEY,
                member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
                trainer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                total_sessions INTEGER NOT NULL,
                private_start_date DATE NOT NULL,
                private_expiry_date DATE NOT NULL,
                status VARCHAR(20) NOT NULL DEFAULT 'ASSIGNED',
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_private_training_subscriptions_total_sessions CHECK (total_sessions > 0),
                CONSTRAINT chk_private_training_subscriptions_dates CHECK (private_expiry_date >= private_start_date),
                CONSTRAINT chk_private_training_subscriptions_status CHECK (status IN ('ASSIGNED', 'ACTIVE', 'COMPLETED', 'EXPIRED', 'CANCELLED'))
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS private_training_sessions (
                id SERIAL PRIMARY KEY,
                subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
                trainer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
                checked_in_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(40) NOT NULL,
                approved_at TIMESTAMPTZ NULL,
                rejected_at TIMESTAMPTZ NULL,
                rejection_reason TEXT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT chk_private_training_sessions_status CHECK (status IN ('PENDING_MEMBER_APPROVAL', 'APPROVED', 'REJECTED')),
                CONSTRAINT chk_private_training_sessions_rejection_reason CHECK (
                    status <> 'REJECTED' OR length(btrim(COALESCE(rejection_reason, ''))) > 0
                )
            )
            """
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS private_training_portal_tokens (
                id SERIAL PRIMARY KEY,
                subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
                token_hash CHAR(64) NOT NULL UNIQUE,
                created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
                revoked_at TIMESTAMPTZ NULL,
                last_used_at TIMESTAMPTZ NULL
            )
            """
        )

        # Indexes
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_trainer_status_start
            ON private_training_subscriptions(trainer_user_id, status, private_start_date)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_member_status
            ON private_training_subscriptions(member_id, status)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_expiry_date
            ON private_training_subscriptions(private_expiry_date)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_sessions_subscription_status_checked_in
            ON private_training_sessions(subscription_id, status, checked_in_at DESC)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_private_training_sessions_one_pending_per_subscription
            ON private_training_sessions(subscription_id)
            WHERE status = 'PENDING_MEMBER_APPROVAL'
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_sessions_trainer_checked_in
            ON private_training_sessions(trainer_user_id, checked_in_at DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_private_training_portal_tokens_created_by
            ON private_training_portal_tokens(created_by_user_id)
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_private_training_portal_tokens_active_per_subscription
            ON private_training_portal_tokens(subscription_id)
            WHERE revoked_at IS NULL
            """
        )

        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


def _subscription_view_query(where_clause: str = "", order_clause: str = "ORDER BY s.created_at DESC, s.id DESC") -> str:
    return f"""
        SELECT
            s.*,
            m.name AS member_name,
            m.phone AS member_phone,
            m.email AS member_email,
            m.membership_packages AS gym_membership_packages,
            m.membership_status AS gym_membership_status,
            m.starting_date AS gym_starting_date,
            m.end_date AS gym_end_date,
            t.username AS trainer_username,
            t.email AS trainer_email,
            creator.username AS created_by_username,
            COALESCE(sess.approved_count, 0) AS approved_count,
            COALESCE(sess.pending_count, 0) AS pending_count,
            COALESCE(sess.rejected_count, 0) AS rejected_count,
            COALESCE(tok.active_token_count, 0) AS active_token_count
        FROM private_training_subscriptions s
        JOIN members m ON m.id = s.member_id
        JOIN users t ON t.id = s.trainer_user_id
        LEFT JOIN users creator ON creator.id = s.created_by_user_id
        LEFT JOIN LATERAL (
            SELECT
                COUNT(*) FILTER (WHERE ps.status = 'APPROVED') AS approved_count,
                COUNT(*) FILTER (WHERE ps.status = 'PENDING_MEMBER_APPROVAL') AS pending_count,
                COUNT(*) FILTER (WHERE ps.status = 'REJECTED') AS rejected_count
            FROM private_training_sessions ps
            WHERE ps.subscription_id = s.id
        ) sess ON TRUE
        LEFT JOIN LATERAL (
            SELECT COUNT(*) FILTER (WHERE pt.revoked_at IS NULL) AS active_token_count
            FROM private_training_portal_tokens pt
            WHERE pt.subscription_id = s.id
        ) tok ON TRUE
        {where_clause}
        {order_clause}
    """


def _normalize_subscription_row(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    normalized = dict(row)
    approved_count = int(normalized.get("approved_count") or 0)
    total_sessions = int(normalized.get("total_sessions") or 0)
    normalized["approved_count"] = approved_count
    normalized["remaining_sessions"] = max(total_sessions - approved_count, 0)
    normalized["effective_status"] = calculate_effective_subscription_status(normalized, approved_count=approved_count)
    return normalized


def _load_subscription_counts(cur: RealDictCursor, subscription_id: int) -> dict[str, int]:
    cur.execute(
        """
        SELECT
            COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved_count,
            COUNT(*) FILTER (WHERE status = 'PENDING_MEMBER_APPROVAL') AS pending_count,
            COUNT(*) FILTER (WHERE status = 'REJECTED') AS rejected_count
        FROM private_training_sessions
        WHERE subscription_id = %s
        """,
        (subscription_id,),
    )
    row = cur.fetchone() or {}
    return {
        "approved_count": int(row.get("approved_count") or 0),
        "pending_count": int(row.get("pending_count") or 0),
        "rejected_count": int(row.get("rejected_count") or 0),
    }


def calculate_effective_subscription_status(subscription_row: dict[str, Any], approved_count: int | None = None, cairo_today: date | None = None) -> str:
    """Derives the effective lifecycle state from counts and Cairo date."""
    if not subscription_row:
        return "UNKNOWN"

    if str(subscription_row.get("status") or "").upper() == "CANCELLED":
        return "CANCELLED"

    approved = int(approved_count if approved_count is not None else subscription_row.get("approved_count") or 0)
    total_sessions = int(subscription_row.get("total_sessions") or 0)
    if approved >= total_sessions and total_sessions > 0:
        return "COMPLETED"

    today = cairo_today or get_cairo_date()
    expiry = subscription_row.get("private_expiry_date")
    start = subscription_row.get("private_start_date")
    if expiry and today > expiry:
        return "EXPIRED"
    if start and today >= start:
        return "ACTIVE"
    return "ASSIGNED"


def get_private_training_approved_count(subscription_id: int) -> int:
    row = query_db(
        """
        SELECT COUNT(*) AS count
        FROM private_training_sessions
        WHERE subscription_id = %s
          AND status = 'APPROVED'
        """,
        (subscription_id,),
        one=True,
    )
    return int(row["count"]) if row else 0


def get_private_training_remaining_sessions(subscription_row: dict[str, Any]) -> int:
    approved_count = int(subscription_row.get("approved_count") or 0)
    total_sessions = int(subscription_row.get("total_sessions") or 0)
    return max(total_sessions - approved_count, 0)


def get_private_training_subscription(subscription_id: int) -> dict[str, Any] | None:
    query = _subscription_view_query("WHERE s.id = %s")
    return _normalize_subscription_row(query_db(query, (subscription_id,), one=True))


def get_private_training_subscription_for_member(member_id: int) -> dict[str, Any] | None:
    query = _subscription_view_query("WHERE s.member_id = %s", "ORDER BY s.created_at DESC, s.id DESC")
    return _normalize_subscription_row(query_db(query, (member_id,), one=True))


def get_private_training_subscription_for_trainer(trainer_user_id: int, subscription_id: int) -> dict[str, Any] | None:
    query = _subscription_view_query("WHERE s.id = %s AND s.trainer_user_id = %s")
    return _normalize_subscription_row(query_db(query, (subscription_id, trainer_user_id), one=True))


def list_private_training_subscriptions_for_trainer(trainer_user_id: int) -> list[dict[str, Any]]:
    query = _subscription_view_query("WHERE s.trainer_user_id = %s")
    rows = query_db(query, (trainer_user_id,)) or []
    return [_normalize_subscription_row(row) for row in rows if row]


def list_private_training_subscriptions_for_member(member_id: int) -> list[dict[str, Any]]:
    query = _subscription_view_query("WHERE s.member_id = %s")
    rows = query_db(query, (member_id,)) or []
    return [_normalize_subscription_row(row) for row in rows if row]


def get_private_training_sessions(subscription_id: int) -> list[dict[str, Any]]:
    return query_db(
        """
        SELECT *
        FROM private_training_sessions
        WHERE subscription_id = %s
        ORDER BY checked_in_at DESC, id DESC
        """,
        (subscription_id,),
    ) or []


def get_private_training_pending_session(subscription_id: int) -> dict[str, Any] | None:
    return query_db(
        """
        SELECT *
        FROM private_training_sessions
        WHERE subscription_id = %s
          AND status = 'PENDING_MEMBER_APPROVAL'
        ORDER BY checked_in_at DESC, id DESC
        LIMIT 1
        """,
        (subscription_id,),
        one=True,
    )


def get_private_training_active_subscription_for_member(member_id: int) -> dict[str, Any] | None:
    """Returns a currently live subscription if one exists for the member."""
    rows = query_db(
        f"""
        SELECT
            s.*,
            COALESCE(sess.approved_count, 0) AS approved_count
        FROM private_training_subscriptions s
        LEFT JOIN LATERAL (
            SELECT COUNT(*) FILTER (WHERE ps.status = 'APPROVED') AS approved_count
            FROM private_training_sessions ps
            WHERE ps.subscription_id = s.id
        ) sess ON TRUE
        WHERE s.member_id = %s
          AND s.status <> 'CANCELLED'
          AND s.private_expiry_date >= {CAIRO_TODAY_SQL}
        ORDER BY s.created_at DESC, s.id DESC
        """,
        (member_id,),
    ) or []
    for row in rows:
        normalized = dict(row)
        if calculate_effective_subscription_status(normalized, approved_count=normalized.get("approved_count")) in ("ASSIGNED", "ACTIVE"):
            return _normalize_subscription_row(normalized)
    return None


def get_private_training_token_by_hash(token_hash: str) -> dict[str, Any] | None:
    return query_db(
        """
        SELECT
            pt.*,
            s.member_id,
            s.trainer_user_id,
            s.created_by_user_id AS subscription_created_by_user_id,
            s.total_sessions,
            s.private_start_date,
            s.private_expiry_date,
            s.status AS subscription_status,
            COALESCE(sess.approved_count, 0) AS approved_count
        FROM private_training_portal_tokens pt
        JOIN private_training_subscriptions s ON s.id = pt.subscription_id
        LEFT JOIN LATERAL (
            SELECT COUNT(*) FILTER (WHERE ps.status = 'APPROVED') AS approved_count
            FROM private_training_sessions ps
            WHERE ps.subscription_id = s.id
        ) sess ON TRUE
        WHERE pt.token_hash = %s
          AND pt.revoked_at IS NULL
        LIMIT 1
        """,
        (token_hash,),
        one=True,
    )


def get_active_private_training_token(subscription_id: int) -> dict[str, Any] | None:
    return query_db(
        """
        SELECT *
        FROM private_training_portal_tokens
        WHERE subscription_id = %s
          AND revoked_at IS NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (subscription_id,),
        one=True,
    )


def lock_private_training_subscription(cur: RealDictCursor, subscription_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT *
        FROM private_training_subscriptions
        WHERE id = %s
        FOR UPDATE
        """,
        (subscription_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    normalized = dict(row)
    normalized.update(_load_subscription_counts(cur, subscription_id))
    return _normalize_subscription_row(normalized)


def lock_private_training_session(cur: RealDictCursor, session_id: int) -> dict[str, Any] | None:
    cur.execute(
        """
        SELECT *
        FROM private_training_sessions
        WHERE id = %s
        FOR UPDATE
        """,
        (session_id,),
    )
    return cur.fetchone()


def lock_private_training_subscriptions_for_member(cur: RealDictCursor, member_id: int) -> list[dict[str, Any]]:
    cur.execute(
        """
        SELECT *
        FROM private_training_subscriptions
        WHERE member_id = %s
        ORDER BY created_at DESC, id DESC
        FOR UPDATE
        """,
        (member_id,),
    )
    rows = cur.fetchall() or []
    normalized_rows = []
    for row in rows:
        normalized = dict(row)
        normalized.update(_load_subscription_counts(cur, normalized["id"]))
        normalized_rows.append(_normalize_subscription_row(normalized))
    return [row for row in normalized_rows if row]
