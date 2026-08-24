"""Validation helpers for the Private Training domain."""

from datetime import date, datetime
from typing import Any

SUBSCRIPTION_STATUSES = ("ASSIGNED", "ACTIVE", "COMPLETED", "EXPIRED", "CANCELLED")
SESSION_STATUSES = ("PENDING_MEMBER_APPROVAL", "APPROVED", "REJECTED")


def parse_private_date(value: Any, field_name: str) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if value is None:
        raise ValueError(f"{field_name} is required")
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a valid date")

    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} is required")

    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(cleaned[:10], fmt).date()
        except ValueError:
            continue

    raise ValueError(f"{field_name} must be a valid date in YYYY-MM-DD format")


def validate_positive_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be a positive integer") from exc
    if parsed <= 0:
        raise ValueError(f"{field_name} must be greater than 0")
    return parsed


def validate_non_negative_int(value: Any, field_name: str) -> int:
    try:
        parsed = int(value)
    except Exception as exc:
        raise ValueError(f"{field_name} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return parsed


def validate_date_range(start_date: date, expiry_date: date) -> None:
    if expiry_date < start_date:
        raise ValueError("private_expiry_date must be on or after private_start_date")


def validate_rejection_reason(reason: Any) -> str:
    if reason is None:
        raise ValueError("rejection_reason is required")
    reason_text = str(reason).strip()
    if not reason_text:
        raise ValueError("rejection_reason is required")
    return reason_text


def validate_status(value: Any, allowed_values: tuple[str, ...], field_name: str) -> str:
    status = str(value).strip().upper()
    if status not in allowed_values:
        raise ValueError(f"{field_name} must be one of: {', '.join(allowed_values)}")
    return status
