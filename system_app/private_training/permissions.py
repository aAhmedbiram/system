"""Permission helpers for the Private Training domain."""

from typing import Any, Mapping

PRIVATE_TRAINING_VIEW = "private_training_view"
PRIVATE_TRAINING_MANAGE = "private_training_manage"
PRIVATE_TRAINING_TRAINER = "private_training_trainer"

PRIVATE_TRAINING_PERMISSION_LABELS = {
    PRIVATE_TRAINING_VIEW: "Private Training - View",
    PRIVATE_TRAINING_MANAGE: "Private Training - Manage",
    PRIVATE_TRAINING_TRAINER: "Private Training - Trainer",
}


def _load_permissions(raw_permissions: Any) -> dict:
    if not raw_permissions:
        return {}
    if isinstance(raw_permissions, dict):
        return raw_permissions
    import json

    try:
        loaded = json.loads(raw_permissions)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def is_super_user(user: Mapping[str, Any] | None) -> bool:
    if not user:
        return False
    if user.get("username") == "rino":
        return True
    perms = _load_permissions(user.get("permissions"))
    return bool(perms.get("super_admin"))


def has_private_training_permission(user: Mapping[str, Any] | None, permission_key: str) -> bool:
    if not user:
        return False
    if is_super_user(user):
        return True
    perms = _load_permissions(user.get("permissions"))
    return bool(perms.get(permission_key))


def can_manage_private_training(user: Mapping[str, Any] | None) -> bool:
    return has_private_training_permission(user, PRIVATE_TRAINING_MANAGE)


def can_train_private_training(user: Mapping[str, Any] | None) -> bool:
    return has_private_training_permission(user, PRIVATE_TRAINING_TRAINER)


def can_view_private_training(user: Mapping[str, Any] | None) -> bool:
    if not user:
        return False
    return bool(
        is_super_user(user)
        or has_private_training_permission(user, PRIVATE_TRAINING_VIEW)
        or can_manage_private_training(user)
        or can_train_private_training(user)
    )


def is_approved_user(user: Mapping[str, Any] | None) -> bool:
    if not user:
        return False
    return bool(user.get("is_approved") or user.get("username") == "rino")
