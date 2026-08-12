import re

VALID_LEAD_STAGES = [
    'NEW',
    'CONTACTED',
    'FOLLOW_UP',
    'INTERESTED',
    'TRIAL',
    'WON',
    'LOST'
]

VALID_ACTIVITY_TYPES = [
    'CALL',
    'WHATSAPP',
    'VISIT',
    'NOTE',
    'FOLLOW_UP',
    'STAGE_CHANGE',
    'ASSIGNED',
    'REASSIGNED',
    'CONVERTED',
    'REACTIVATED',
    'LOST',
    'REOPENED'
]

def validate_required_string(val, name):
    if val is None:
        raise ValueError(f"'{name}' is required")
    val_str = str(val).strip()
    if not val_str:
        raise ValueError(f"'{name}' cannot be empty")
    return val_str

def validate_optional_string(val):
    if val is None:
        return None
    return str(val).strip()

def validate_email(val):
    if not val:
        return None
    email_str = str(val).strip()
    if not email_str:
        return None
    # Basic email regex
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email_str):
        raise ValueError("Invalid email format")
    return email_str

def validate_positive_int(val, name):
    if val is None:
        return None
    try:
        val_int = int(val)
        if val_int <= 0:
            raise ValueError()
        return val_int
    except (ValueError, TypeError):
        raise ValueError(f"'{name}' must be a positive integer")

def validate_pagination(page_param, per_page_param):
    try:
        page = int(page_param) if page_param is not None else 1
        if page < 1:
            page = 1
    except (ValueError, TypeError):
        page = 1

    try:
        per_page = int(per_page_param) if per_page_param is not None else 25
        if per_page < 1:
            per_page = 25
        elif per_page > 100:
            per_page = 100
    except (ValueError, TypeError):
        per_page = 25

    return page, per_page

def validate_stage_filter(stage):
    if not stage:
        return None
    stage_upper = str(stage).upper().strip()
    if stage_upper not in VALID_LEAD_STAGES:
        raise ValueError(f"Invalid stage filter: {stage}")
    return stage_upper

def validate_member_status_filter(status):
    if not status:
        return None
    status_lower = str(status).lower().strip()
    if status_lower not in ['member', 'prospect']:
        raise ValueError("member_status must be 'member' or 'prospect'")
    return status_lower

def validate_integer_list(val, name):
    if val is None:
        raise ValueError(f"'{name}' is required")
    if not isinstance(val, list):
        raise ValueError(f"'{name}' must be a list")
    if not val:
        raise ValueError(f"'{name}' cannot be empty")
    if len(val) > 200:
        raise ValueError(f"'{name}' cannot exceed 200 items")
    try:
        cleaned = []
        for x in val:
            x_int = int(x)
            cleaned.append(x_int)
        return cleaned
    except (ValueError, TypeError):
        raise ValueError(f"'{name}' must contain integers only")

USER_ACTIVITY_TYPES = {
    'CALL',
    'WHATSAPP',
    'VISIT',
    'NOTE',
    'FOLLOW_UP'
}

def validate_user_activity_type(val):
    if not val:
        raise ValueError("'activity_type' is required")
    val_upper = str(val).upper().strip()
    if val_upper not in USER_ACTIVITY_TYPES:
        raise ValueError(f"Invalid activity type: {val}. Allowed: {', '.join(USER_ACTIVITY_TYPES)}")
    return val_upper

def validate_iso_timestamp(val):
    if val is None:
        return None
    import datetime
    try:
        dt = datetime.datetime.fromisoformat(str(val))
        if dt.tzinfo is None or dt.tzinfo.utcoffset(dt) is None:
            raise ValueError("Timestamp must be timezone-aware (e.g. +03:00)")
        return dt
    except Exception as e:
        raise ValueError(f"Invalid timezone-aware ISO-8601 timestamp: {e}")

def validate_future_timestamp(dt):
    if dt is None:
        return None
    import datetime
    now = datetime.datetime.now(datetime.timezone.utc)
    if dt < now:
        raise ValueError("Scheduled follow-up time cannot be in the past")
    return dt
