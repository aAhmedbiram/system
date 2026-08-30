"""Business logic for the Private Training domain."""

from __future__ import annotations

import hashlib
import secrets
import re
from datetime import datetime
from typing import Any

from psycopg2 import IntegrityError

from system_app.crm.queries import run_in_transaction
from system_app.func import get_cairo_date
from system_app.queries import get_member, query_db

from .permissions import (
    PRIVATE_TRAINING_MANAGE,
    PRIVATE_TRAINING_TRAINER,
    PRIVATE_TRAINING_VIEW,
    can_manage_private_training,
    can_train_private_training,
    has_private_training_permission,
    is_approved_user,
    is_super_user,
)
from .queries import (
    calculate_effective_subscription_status,
    _display_user_name,
    _subscription_view_query,
    get_private_training_approved_count,
    get_private_training_pending_session,
    get_private_training_remaining_sessions,
    get_private_training_sessions,
    get_private_training_subscription,
    get_private_training_subscription_for_member,
    get_private_training_subscription_for_trainer,
    get_private_training_token_by_hash,
    list_private_training_subscriptions_for_trainer,
    lock_private_training_session,
    lock_private_training_subscription,
    lock_private_training_subscriptions_for_member,
)
from .validators import (
    parse_private_date,
    validate_date_range,
    validate_positive_int,
    validate_rejection_reason,
)


class PrivateTrainingError(Exception):
    error_code = "private_training_error"

    def __init__(self, message: str, error_code: str | None = None, details: dict[str, Any] | None = None):
        super().__init__(message)
        if error_code:
            self.error_code = error_code
        self.details = details or {}


class PrivateTrainingValidationError(PrivateTrainingError):
    error_code = "invalid_input"


class PrivateTrainingForbiddenError(PrivateTrainingError):
    error_code = "forbidden"


class PrivateTrainingNotFoundError(PrivateTrainingError):
    error_code = "not_found"


class PrivateTrainingConflictError(PrivateTrainingError):
    error_code = "conflict"


class PrivateTrainingInvalidTrainerError(PrivateTrainingValidationError):
    error_code = "invalid_trainer"


class PrivateTrainingSubscriptionConflictError(PrivateTrainingConflictError):
    error_code = "active_subscription_conflict"


class PrivateTrainingPendingSessionConflictError(PrivateTrainingConflictError):
    error_code = "pending_session_conflict"


class PrivateTrainingExpiredError(PrivateTrainingConflictError):
    error_code = "subscription_expired"


class PrivateTrainingCompletedError(PrivateTrainingConflictError):
    error_code = "subscription_completed"


class PrivateTrainingCancelledError(PrivateTrainingConflictError):
    error_code = "subscription_cancelled"


class PrivateTrainingAlreadyProcessedError(PrivateTrainingConflictError):
    error_code = "session_already_processed"


_PRIVATE_TRAINING_CLIENT_TYPES = ("MEMBER", "OUTCOMER")


def _normalize_user(user: dict[str, Any] | None) -> dict[str, Any] | None:
    return dict(user) if user else None


def _require_managed_current_user(current_user: dict[str, Any]) -> None:
    if not current_user:
        raise PrivateTrainingForbiddenError("Login required")
    if not (is_super_user(current_user) or can_manage_private_training(current_user)):
        raise PrivateTrainingForbiddenError("Current user cannot manage private training subscriptions")
    if not is_approved_user(current_user):
        raise PrivateTrainingForbiddenError("Current user is not approved")


def _require_trainer_current_user(current_user: dict[str, Any]) -> None:
    if not current_user:
        raise PrivateTrainingForbiddenError("Login required")
    if not (is_super_user(current_user) or can_train_private_training(current_user)):
        raise PrivateTrainingForbiddenError("Current user is not allowed to manage trainer workflows")
    if not is_approved_user(current_user):
        raise PrivateTrainingForbiddenError("Current user is not approved")


def _load_user(user_id: int) -> dict[str, Any] | None:
    return query_db(
        "SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s",
        (user_id,),
        one=True,
    )


def _load_trainer_user(trainer_user_id: int) -> dict[str, Any]:
    user = _load_user(trainer_user_id)
    if not user:
        raise PrivateTrainingInvalidTrainerError("Trainer user does not exist")
    if not is_approved_user(user):
        raise PrivateTrainingInvalidTrainerError("Trainer user is not approved")
    if not can_train_private_training(user):
        raise PrivateTrainingInvalidTrainerError("Trainer user does not have private_training_trainer permission")
    return user


def _load_member(member_id: int) -> dict[str, Any]:
    member = get_member(member_id)
    if not member:
        raise PrivateTrainingNotFoundError("Member not found")
    return dict(member)


def _normalize_client_type(client_type: Any) -> str:
    if client_type is None:
        return "MEMBER"
    client_type_text = str(client_type).strip().upper()
    if client_type_text not in _PRIVATE_TRAINING_CLIENT_TYPES:
        raise PrivateTrainingValidationError("client_type must be MEMBER or OUTCOMER")
    return client_type_text


def _normalize_client_name(client_name: Any, *, field_name: str = "client_name") -> str:
    if client_name is None:
        raise PrivateTrainingValidationError(f"{field_name} is required")
    client_name_text = str(client_name).strip()
    if not client_name_text:
        raise PrivateTrainingValidationError(f"{field_name} is required")
    if len(client_name_text) > 255:
        raise PrivateTrainingValidationError(f"{field_name} must be 255 characters or fewer")
    return client_name_text


def _normalize_client_phone(client_phone: Any, *, field_name: str = "client_phone", required: bool = True) -> str:
    if client_phone is None:
        if required:
            raise PrivateTrainingValidationError(f"{field_name} is required")
        return ""
    client_phone_text = str(client_phone).strip()
    if required and not client_phone_text:
        raise PrivateTrainingValidationError(f"{field_name} is required")
    if len(client_phone_text) > 50:
        raise PrivateTrainingValidationError(f"{field_name} must be 50 characters or fewer")
    return client_phone_text


def _normalize_phone_identity(client_phone: Any) -> str:
    phone_text = str(client_phone or "")
    return re.sub(r"\D+", "", phone_text)


def _current_cairo_date():
    return get_cairo_date()


def can_write_private_training_daily_workout(current_user: dict[str, Any] | None, subscription_row: dict[str, Any] | None) -> bool:
    if not current_user or not subscription_row:
        return False
    if not is_approved_user(current_user):
        return False
    if is_super_user(current_user) or can_manage_private_training(current_user):
        return True
    return bool(
        can_train_private_training(current_user)
        and subscription_row.get("trainer_user_id") == current_user.get("id")
    )


def list_private_training_trainer_options(current_user: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    if current_user and not (
        is_super_user(current_user)
        or can_manage_private_training(current_user)
        or has_private_training_permission(current_user, PRIVATE_TRAINING_VIEW)
        or can_train_private_training(current_user)
    ):
        raise PrivateTrainingForbiddenError("Current user cannot view private training trainers")

    rows = query_db(
        """
        SELECT id, username, email, permissions
        FROM users
        WHERE is_approved = TRUE
        ORDER BY username ASC, id ASC
        """,
    ) or []
    trainers: list[dict[str, Any]] = []
    for row in rows:
        row_dict = dict(row)
        if can_train_private_training(row_dict):
            trainers.append(
                {
                    "id": row_dict.get("id"),
                    "username": row_dict.get("username"),
                    "email": row_dict.get("email"),
                    "display_name": _display_user_name(row_dict.get("username")) or row_dict.get("username") or f"User {row_dict.get('id')}",
                }
            )
    return trainers


def _subscription_is_live(subscription_row: dict[str, Any]) -> bool:
    if not subscription_row:
        return False
    effective_status = calculate_effective_subscription_status(
        subscription_row,
        approved_count=subscription_row.get("approved_count"),
        cairo_today=_current_cairo_date(),
    )
    return effective_status in ("ASSIGNED", "ACTIVE")


def _subscription_is_usable_for_portal(subscription_row: dict[str, Any]) -> bool:
    if not subscription_row:
        return False
    effective_status = calculate_effective_subscription_status(
        subscription_row,
        approved_count=subscription_row.get("approved_count"),
        cairo_today=_current_cairo_date(),
    )
    return effective_status in ("ASSIGNED", "ACTIVE")


def get_subscription_effective_status(subscription_row: dict[str, Any]) -> str:
    return calculate_effective_subscription_status(
        subscription_row,
        approved_count=subscription_row.get("approved_count"),
        cairo_today=_current_cairo_date(),
    )


def approved_session_count(subscription_id: int) -> int:
    return get_private_training_approved_count(subscription_id)


def remaining_sessions(subscription_row_or_id: int | dict[str, Any]) -> int:
    if isinstance(subscription_row_or_id, dict):
        return get_private_training_remaining_sessions(subscription_row_or_id)
    subscription = get_private_training_subscription(subscription_row_or_id)
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")
    return get_private_training_remaining_sessions(subscription)


def get_private_training_todays_workout(subscription_id: int) -> dict[str, Any] | None:
    return get_private_training_daily_workout(subscription_id, _current_cairo_date())


def _normalize_workout_name(workout_name: Any) -> str:
    if workout_name is None:
        raise PrivateTrainingValidationError("workout_name is required")
    workout_text = str(workout_name).strip()
    if not workout_text:
        raise PrivateTrainingValidationError("workout_name is required")
    if len(workout_text) > 255:
        raise PrivateTrainingValidationError("workout_name must be 255 characters or fewer")
    return workout_text


def _normalize_daily_workout_name(workout_name: Any) -> str:
    return _normalize_workout_name(workout_name)


def save_private_training_todays_workout(
    current_user: dict[str, Any],
    subscription_id: Any,
    workout_name: Any,
) -> dict[str, Any]:
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")
    subscription = get_private_training_subscription(subscription_id_int)
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")
    if not can_write_private_training_daily_workout(current_user, subscription):
        raise PrivateTrainingForbiddenError("Current user cannot edit today's workout for this subscription")

    normalized_workout_name = _normalize_workout_name(workout_name)
    workout = upsert_private_training_daily_workout(
        subscription_id_int,
        normalized_workout_name,
        _current_cairo_date(),
    )
    if not workout:
        raise PrivateTrainingError("Failed to save today's workout")
    return {
        "subscription": subscription,
        "workout": workout,
    }


def create_private_training_subscription(
    current_user: dict[str, Any],
    member_id: Any,
    trainer_user_id: Any,
    total_sessions: Any,
    private_start_date: Any,
    private_expiry_date: Any,
    client_type: Any = "MEMBER",
    client_name: Any = None,
    client_phone: Any = None,
) -> dict[str, Any]:
    _require_managed_current_user(current_user)

    client_type_text = _normalize_client_type(client_type)
    trainer_user_id_int = validate_positive_int(trainer_user_id, "trainer_user_id")
    total_sessions_int = validate_positive_int(total_sessions, "total_sessions")
    start_date = parse_private_date(private_start_date, "private_start_date")
    expiry_date = parse_private_date(private_expiry_date, "private_expiry_date")
    validate_date_range(start_date, expiry_date)

    trainer = _load_trainer_user(trainer_user_id_int)
    today = _current_cairo_date()
    if expiry_date < today:
        raise PrivateTrainingExpiredError("Cannot create an already expired private subscription")

    stored_status = "ACTIVE" if start_date <= today else "ASSIGNED"
    member = None
    member_id_int = None
    client_name_text = ""
    client_phone_text = ""

    if client_type_text == "MEMBER":
        member_id_int = validate_positive_int(member_id, "member_id")
        member = _load_member(member_id_int)
        client_name_text = _normalize_client_name(member.get("name"), field_name="client_name")
        client_phone_text = _normalize_client_phone(member.get("phone"), field_name="client_phone", required=False)
    else:
        if member_id not in (None, "", 0):
            raise PrivateTrainingValidationError("member_id must be empty for outcomer subscriptions")
        client_name_text = _normalize_client_name(client_name)
        client_phone_text = _normalize_client_phone(client_phone)
        if not _normalize_phone_identity(client_phone_text):
            raise PrivateTrainingValidationError("client_phone must contain digits")

    def _create(cur):
        if client_type_text == "MEMBER":
            cur.execute("SELECT id FROM members WHERE id = %s FOR UPDATE", (member_id_int,))
            if not cur.fetchone():
                raise PrivateTrainingNotFoundError("Member not found")

            cur.execute(
                """
                SELECT *
                FROM private_training_subscriptions
                WHERE member_id = %s
                ORDER BY created_at DESC, id DESC
                """,
                (member_id_int,),
            )
            existing_rows = cur.fetchall() or []
            for row in existing_rows:
                row_dict = dict(row)
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved_count
                    FROM private_training_sessions
                    WHERE subscription_id = %s
                    """,
                    (row_dict["id"],),
                )
                counts = cur.fetchone() or {}
                row_dict["approved_count"] = int(counts.get("approved_count") or 0)
                if _subscription_is_live(row_dict):
                    raise PrivateTrainingSubscriptionConflictError(
                        "Member already has an effective active private subscription",
                        details={"existing_subscription_id": row_dict.get("id")},
                    )
        else:
            normalized_phone_identity = _normalize_phone_identity(client_phone_text)
            lock_key = f"pt_outcomer_phone:{normalized_phone_identity}"
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (lock_key,))
            cur.execute(
                """
                SELECT *
                FROM private_training_subscriptions
                WHERE client_type = 'OUTCOMER'
                  AND regexp_replace(COALESCE(client_phone, ''), '[^0-9]+', '', 'g') = %s
                ORDER BY created_at DESC, id DESC
                """,
                (normalized_phone_identity,),
            )
            existing_rows = cur.fetchall() or []
            for row in existing_rows:
                row_dict = dict(row)
                cur.execute(
                    """
                    SELECT COUNT(*) FILTER (WHERE status = 'APPROVED') AS approved_count
                    FROM private_training_sessions
                    WHERE subscription_id = %s
                    """,
                    (row_dict["id"],),
                )
                counts = cur.fetchone() or {}
                row_dict["approved_count"] = int(counts.get("approved_count") or 0)
                if _subscription_is_live(row_dict):
                    raise PrivateTrainingSubscriptionConflictError(
                        "Outcomer already has an effective active private subscription",
                        details={"existing_subscription_id": row_dict.get("id")},
                    )

        cur.execute(
            """
            INSERT INTO private_training_subscriptions (
                member_id, client_type, client_name, client_phone, trainer_user_id, created_by_user_id,
                total_sessions, private_start_date, private_expiry_date, status
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, member_id, client_type, client_name, client_phone, trainer_user_id, created_by_user_id, total_sessions,
                      private_start_date, private_expiry_date, status, created_at, updated_at
            """,
            (
                member_id_int,
                client_type_text,
                client_name_text,
                client_phone_text,
                trainer_user_id_int,
                current_user["id"],
                total_sessions_int,
                start_date,
                expiry_date,
                stored_status,
            ),
        )
        created = cur.fetchone()
        return dict(created) if created else None

    subscription = run_in_transaction(_create)
    if not subscription:
        raise PrivateTrainingError("Subscription creation failed")
    subscription_row = get_private_training_subscription(subscription["id"])
    if not subscription_row:
        subscription_row = dict(subscription)
    return {
        "subscription": subscription_row,
        "member": member,
        "client": {
            "client_type": client_type_text,
            "client_name": client_name_text,
            "client_phone": client_phone_text,
        },
        "trainer": trainer,
    }


def cancel_private_training_subscription(current_user: dict[str, Any], subscription_id: Any) -> dict[str, Any]:
    _require_managed_current_user(current_user)
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")

    def _cancel(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")

        effective_status = get_subscription_effective_status(subscription)
        if effective_status == "CANCELLED":
            raise PrivateTrainingCancelledError("Subscription is cancelled")
        if effective_status == "COMPLETED":
            raise PrivateTrainingCompletedError("Subscription is completed")
        if effective_status == "EXPIRED":
            raise PrivateTrainingExpiredError("Subscription is expired")
        if effective_status not in ("ASSIGNED", "ACTIVE"):
            raise PrivateTrainingConflictError("Subscription cannot be cancelled")

        cur.execute(
            """
            UPDATE private_training_subscriptions
            SET status = 'CANCELLED',
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id
            """,
            (subscription_id_int,),
        )
        updated = cur.fetchone()
        cancelled_subscription = dict(subscription)
        cancelled_subscription["status"] = "CANCELLED"
        cancelled_subscription["effective_status"] = "CANCELLED"
        return {
            "subscription": cancelled_subscription,
            "outcome": "cancelled",
            "updated": bool(updated),
        }

    result = run_in_transaction(_cancel)
    if not result or not result.get("subscription"):
        raise PrivateTrainingError("Failed to cancel private training subscription")
    return result


def list_private_clients_for_trainer(
    current_user: dict[str, Any],
    *,
    trainer_user_id: Any | None = None,
    client_type: Any | None = None,
) -> list[dict[str, Any]]:
    if not current_user:
        raise PrivateTrainingForbiddenError("Login required")
    if not (
        is_super_user(current_user)
        or has_private_training_permission(current_user, PRIVATE_TRAINING_VIEW)
        or can_manage_private_training(current_user)
        or can_train_private_training(current_user)
    ):
        raise PrivateTrainingForbiddenError("Current user cannot view private training subscriptions")

    normalized_trainer_user_id = None
    if trainer_user_id not in (None, ""):
        normalized_trainer_user_id = validate_positive_int(trainer_user_id, "trainer_user_id")

    normalized_client_type = None
    if client_type not in (None, ""):
        normalized_client_type = _normalize_client_type(client_type)

    where_parts: list[str] = []
    params: list[Any] = []

    if is_super_user(current_user) or has_private_training_permission(current_user, PRIVATE_TRAINING_VIEW) or can_manage_private_training(current_user):
        pass
    else:
        where_parts.append("s.trainer_user_id = %s")
        params.append(current_user["id"])

    if normalized_trainer_user_id is not None:
        where_parts.append("s.trainer_user_id = %s")
        params.append(normalized_trainer_user_id)

    if normalized_client_type is not None:
        where_parts.append("s.client_type = %s")
        params.append(normalized_client_type)

    where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    rows = query_db(_subscription_view_query(where_clause), tuple(params)) or []
    normalized_rows = []
    for row in rows:
        row_dict = dict(row)
        approved_count = int(row_dict.get("approved_count") or 0)
        total_sessions = int(row_dict.get("total_sessions") or 0)
        row_dict["approved_count"] = approved_count
        row_dict["remaining_sessions"] = max(total_sessions - approved_count, 0)
        row_dict["effective_status"] = calculate_effective_subscription_status(
            row_dict,
            approved_count=approved_count,
            cairo_today=_current_cairo_date(),
        )
        normalized_rows.append(row_dict)
    return normalized_rows


def get_private_subscription_for_trainer(current_user: dict[str, Any], subscription_id: int) -> dict[str, Any]:
    if not current_user:
        raise PrivateTrainingForbiddenError("Login required")

    subscription = get_private_training_subscription(subscription_id)
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")

    if (
        is_super_user(current_user)
        or has_private_training_permission(current_user, PRIVATE_TRAINING_VIEW)
        or can_manage_private_training(current_user)
    ):
        return subscription

    if subscription.get("trainer_user_id") != current_user.get("id"):
        raise PrivateTrainingForbiddenError("Current user cannot access this subscription")
    return subscription


def _subscription_has_pending_session(cur, subscription_id: int) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM private_training_sessions
        WHERE subscription_id = %s
          AND status = 'PENDING_MEMBER_APPROVAL'
        LIMIT 1
        """,
        (subscription_id,),
    )
    return cur.fetchone() is not None


def create_private_training_session_checkin(
    current_user: dict[str, Any],
    subscription_id: Any,
    workout_name: Any,
) -> dict[str, Any]:
    _require_trainer_current_user(current_user)
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")
    normalized_workout_name = _normalize_workout_name(workout_name)

    def _create(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")
        if not (is_super_user(current_user) or subscription.get("trainer_user_id") == current_user.get("id")):
            raise PrivateTrainingForbiddenError("Current user cannot check in this subscription")

        effective_status = get_subscription_effective_status(subscription)
        if effective_status == "CANCELLED":
            raise PrivateTrainingCancelledError("Subscription is cancelled")
        if effective_status == "COMPLETED":
            raise PrivateTrainingCompletedError("Subscription is completed")
        if effective_status == "EXPIRED":
            raise PrivateTrainingExpiredError("Subscription is expired")
        if effective_status != "ACTIVE":
            raise PrivateTrainingConflictError("Subscription is not active")

        approved_count = int(subscription.get("approved_count") or 0)
        if approved_count >= int(subscription.get("total_sessions") or 0):
            raise PrivateTrainingCompletedError("Subscription has no remaining sessions")

        if _subscription_has_pending_session(cur, subscription_id_int):
            raise PrivateTrainingPendingSessionConflictError("A pending session already exists")

        try:
            cur.execute(
                """
                INSERT INTO private_training_sessions (
                    subscription_id, trainer_user_id, workout_name, status, checked_in_at
                ) VALUES (%s, %s, %s, 'PENDING_MEMBER_APPROVAL', CURRENT_TIMESTAMP)
                RETURNING id, subscription_id, trainer_user_id, checked_in_at, status,
                          approved_at, rejected_at, rejection_reason, workout_name, created_at, updated_at
                """,
                (subscription_id_int, current_user["id"], normalized_workout_name),
            )
            session_row = cur.fetchone()
        except IntegrityError as exc:
            pgcode = getattr(exc, "pgcode", None)
            constraint_name = getattr(getattr(exc, "diag", None), "constraint_name", None)
            if pgcode == "23505" or constraint_name == "idx_private_training_sessions_one_pending_per_subscription":
                raise PrivateTrainingPendingSessionConflictError("A pending session already exists") from exc
            raise

        return dict(session_row) if session_row else None

    session_row = run_in_transaction(_create)
    if not session_row:
        raise PrivateTrainingError("Failed to create private training session")
    return session_row


def approve_private_training_session(
    subscription_id: Any,
    session_id: Any,
    portal_authorization_context: dict[str, Any] | None,
) -> dict[str, Any]:
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")
    session_id_int = validate_positive_int(session_id, "session_id")

    if not portal_authorization_context:
        raise PrivateTrainingForbiddenError("Portal authorization context is required")
    if validate_positive_int(portal_authorization_context.get("subscription_id"), "portal_subscription_id") != subscription_id_int:
        raise PrivateTrainingForbiddenError("Portal authorization does not match this subscription")

    def _approve(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")
        session_row = lock_private_training_session(cur, session_id_int)
        if not session_row:
            raise PrivateTrainingNotFoundError("Session not found")
        if session_row.get("subscription_id") != subscription_id_int:
            raise PrivateTrainingForbiddenError("Session does not belong to this subscription")

        if session_row.get("status") == "APPROVED":
            return {
                "session": dict(session_row),
                "subscription": subscription,
                "outcome": "already_approved",
            }
        if session_row.get("status") == "REJECTED":
            raise PrivateTrainingAlreadyProcessedError("Session has already been rejected")
        if session_row.get("status") != "PENDING_MEMBER_APPROVAL":
            raise PrivateTrainingAlreadyProcessedError("Session is not pending")

        effective_status = get_subscription_effective_status(subscription)
        if effective_status == "CANCELLED":
            raise PrivateTrainingCancelledError("Subscription is cancelled")
        if effective_status == "EXPIRED":
            raise PrivateTrainingExpiredError("Subscription is expired")
        if effective_status == "COMPLETED":
            raise PrivateTrainingCompletedError("Subscription is completed")

        approved_count_before = int(subscription.get("approved_count") or 0)
        total_sessions = int(subscription.get("total_sessions") or 0)
        if approved_count_before >= total_sessions:
            raise PrivateTrainingCompletedError("Subscription has no remaining sessions")

        cur.execute(
            """
            UPDATE private_training_sessions
            SET status = 'APPROVED',
                approved_at = CURRENT_TIMESTAMP,
                rejection_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, subscription_id, trainer_user_id, checked_in_at, status,
                      approved_at, rejected_at, rejection_reason, created_at, updated_at
            """,
            (session_id_int,),
        )
        updated_session = cur.fetchone()

        cur.execute(
            """
            SELECT COUNT(*) AS count
            FROM private_training_sessions
            WHERE subscription_id = %s
              AND status = 'APPROVED'
            """,
            (subscription_id_int,),
        )
        approved_after = int(cur.fetchone()["count"] or 0)

        new_status = "COMPLETED" if approved_after >= total_sessions else subscription.get("status")
        if approved_after >= total_sessions:
            cur.execute(
                """
                UPDATE private_training_subscriptions
                SET status = 'COMPLETED',
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                (subscription_id_int,),
            )

        return {
            "session": dict(updated_session) if updated_session else None,
            "subscription": get_private_training_subscription(subscription_id_int),
            "outcome": "approved",
            "approved_count": approved_after,
            "new_subscription_status": new_status,
        }

    result = run_in_transaction(_approve)
    if not result or not result.get("session"):
        raise PrivateTrainingError("Failed to approve session")
    return result


def reject_private_training_session(
    subscription_id: Any,
    session_id: Any,
    rejection_reason: Any,
    portal_authorization_context: dict[str, Any] | None,
) -> dict[str, Any]:
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")
    session_id_int = validate_positive_int(session_id, "session_id")
    reason = validate_rejection_reason(rejection_reason)

    if not portal_authorization_context:
        raise PrivateTrainingForbiddenError("Portal authorization context is required")
    if validate_positive_int(portal_authorization_context.get("subscription_id"), "portal_subscription_id") != subscription_id_int:
        raise PrivateTrainingForbiddenError("Portal authorization does not match this subscription")

    def _reject(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")
        session_row = lock_private_training_session(cur, session_id_int)
        if not session_row:
            raise PrivateTrainingNotFoundError("Session not found")
        if session_row.get("subscription_id") != subscription_id_int:
            raise PrivateTrainingForbiddenError("Session does not belong to this subscription")

        if session_row.get("status") == "REJECTED":
            return {
                "session": dict(session_row),
                "subscription": subscription,
                "outcome": "already_rejected",
            }
        if session_row.get("status") == "APPROVED":
            raise PrivateTrainingAlreadyProcessedError("Session has already been approved")
        if session_row.get("status") != "PENDING_MEMBER_APPROVAL":
            raise PrivateTrainingAlreadyProcessedError("Session is not pending")

        effective_status = get_subscription_effective_status(subscription)
        if effective_status == "CANCELLED":
            raise PrivateTrainingCancelledError("Subscription is cancelled")
        if effective_status == "EXPIRED":
            raise PrivateTrainingExpiredError("Subscription is expired")
        if effective_status == "COMPLETED":
            raise PrivateTrainingCompletedError("Subscription is completed")

        cur.execute(
            """
            UPDATE private_training_sessions
            SET status = 'REJECTED',
                rejected_at = CURRENT_TIMESTAMP,
                rejection_reason = %s,
                approved_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
            RETURNING id, subscription_id, trainer_user_id, checked_in_at, status,
                      approved_at, rejected_at, rejection_reason, created_at, updated_at
            """,
            (reason, session_id_int),
        )
        updated_session = cur.fetchone()
        return {
            "session": dict(updated_session) if updated_session else None,
            "subscription": get_private_training_subscription(subscription_id_int),
            "outcome": "rejected",
        }

    result = run_in_transaction(_reject)
    if not result or not result.get("session"):
        raise PrivateTrainingError("Failed to reject session")
    return result


def generate_portal_token(current_user: dict[str, Any], subscription_id: Any) -> dict[str, Any]:
    _require_trainer_current_user(current_user)
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")

    def _generate(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")
        if not (is_super_user(current_user) or subscription.get("trainer_user_id") == current_user.get("id")):
            raise PrivateTrainingForbiddenError("Current user cannot generate a token for this subscription")

        effective_status = get_subscription_effective_status(subscription)
        if effective_status == "CANCELLED":
            raise PrivateTrainingCancelledError("Subscription is cancelled")
        if effective_status == "COMPLETED":
            raise PrivateTrainingCompletedError("Subscription is completed")
        if effective_status == "EXPIRED":
            raise PrivateTrainingExpiredError("Subscription is expired")

        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        cur.execute(
            """
            UPDATE private_training_portal_tokens
            SET revoked_at = CURRENT_TIMESTAMP,
                last_used_at = last_used_at
            WHERE subscription_id = %s
              AND revoked_at IS NULL
            """,
            (subscription_id_int,),
        )
        cur.execute(
            """
            INSERT INTO private_training_portal_tokens (
                subscription_id, token_hash, created_by_user_id
            ) VALUES (%s, %s, %s)
            RETURNING id, subscription_id, token_hash, created_by_user_id, created_at, revoked_at, last_used_at
            """,
            (subscription_id_int, token_hash, current_user["id"]),
        )
        token_row = cur.fetchone()
        return {
            "raw_token": raw_token,
            "token": dict(token_row) if token_row else None,
            "subscription": subscription,
        }

    result = run_in_transaction(_generate)
    if not result or not result.get("token"):
        raise PrivateTrainingError("Failed to generate portal token")
    return result


def revoke_portal_token(current_user: dict[str, Any], subscription_id: Any) -> dict[str, Any]:
    _require_trainer_current_user(current_user)
    subscription_id_int = validate_positive_int(subscription_id, "subscription_id")

    def _revoke(cur):
        subscription = lock_private_training_subscription(cur, subscription_id_int)
        if not subscription:
            raise PrivateTrainingNotFoundError("Subscription not found")
        if not (is_super_user(current_user) or subscription.get("trainer_user_id") == current_user.get("id")):
            raise PrivateTrainingForbiddenError("Current user cannot revoke a token for this subscription")

        cur.execute(
            """
            UPDATE private_training_portal_tokens
            SET revoked_at = CURRENT_TIMESTAMP
            WHERE subscription_id = %s
              AND revoked_at IS NULL
            RETURNING id
            """,
            (subscription_id_int,),
        )
        rows = cur.fetchall() or []
        return {
            "revoked_count": len(rows),
            "subscription": subscription,
        }

    return run_in_transaction(_revoke)


def resolve_portal_token(raw_token: str) -> dict[str, Any]:
    if not raw_token or not str(raw_token).strip():
        raise PrivateTrainingNotFoundError("Token not found")

    token_hash = hashlib.sha256(str(raw_token).strip().encode("utf-8")).hexdigest()
    token_row = get_private_training_token_by_hash(token_hash)
    if not token_row:
        raise PrivateTrainingNotFoundError("Token not found")

    subscription = get_private_training_subscription(token_row["subscription_id"])
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")

    effective_status = get_subscription_effective_status(subscription)
    if effective_status == "CANCELLED":
        raise PrivateTrainingCancelledError("Subscription is cancelled")
    if effective_status == "COMPLETED":
        raise PrivateTrainingCompletedError("Subscription is completed")
    if effective_status == "EXPIRED":
        raise PrivateTrainingExpiredError("Subscription is expired")

    query_db(
        """
        UPDATE private_training_portal_tokens
        SET last_used_at = CURRENT_TIMESTAMP
        WHERE token_hash = %s
        """,
        (token_hash,),
        commit=True,
    )

    return {
        "token_hash": token_hash,
        "subscription": subscription,
        "member": {
            "id": token_row.get("member_id"),
        },
        "client": {
            "client_type": subscription.get("client_type"),
            "client_name": subscription.get("client_name"),
            "client_phone": subscription.get("client_phone"),
        },
        "trainer": {
            "id": token_row.get("trainer_user_id"),
        },
        "approved_count": int(token_row.get("approved_count") or 0),
        "effective_status": effective_status,
    }


def list_private_training_sessions(subscription_id: int) -> list[dict[str, Any]]:
    return get_private_training_sessions(subscription_id)


def get_private_training_subscription_detail(subscription_id: int) -> dict[str, Any]:
    subscription = get_private_training_subscription(subscription_id)
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")
    return subscription


def get_private_training_subscription_for_current_trainer(current_user: dict[str, Any], subscription_id: int) -> dict[str, Any]:
    subscription = get_private_subscription_for_trainer(current_user, subscription_id)
    if subscription.get("trainer_user_id") != current_user.get("id") and not (
        is_super_user(current_user) or has_private_training_permission(current_user, PRIVATE_TRAINING_VIEW)
    ):
        raise PrivateTrainingForbiddenError("Current user cannot access this subscription")
    return subscription


def current_private_training_counts(subscription_id: int) -> dict[str, Any]:
    subscription = get_private_training_subscription(subscription_id)
    if not subscription:
        raise PrivateTrainingNotFoundError("Subscription not found")
    return {
        "approved_count": approved_session_count(subscription_id),
        "remaining_sessions": remaining_sessions(subscription),
        "effective_status": get_subscription_effective_status(subscription),
    }
