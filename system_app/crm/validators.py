import re
from zoneinfo import ZoneInfo

CAIRO_TZ = ZoneInfo("Africa/Cairo")

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

def validate_assigned_user_filter(val):
    if val is None:
        return None
    if isinstance(val, bool):
        raise ValueError("assigned_user_id must be a positive integer or 'unassigned'")
    value = str(val).strip()
    if not value:
        return None
    if value.lower() == 'unassigned':
        return 'unassigned'
    try:
        user_id = int(value)
    except (ValueError, TypeError):
        raise ValueError("assigned_user_id must be a positive integer or 'unassigned'")
    if user_id <= 0:
        raise ValueError("assigned_user_id must be a positive integer or 'unassigned'")
    return user_id

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
    now = datetime.datetime.now(CAIRO_TZ)
    if dt < now:
        raise ValueError("Scheduled follow-up time cannot be in the past")
    return dt

ACTIVE_LEAD_STAGES = {'NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL'}
TERMINAL_LEAD_STAGES = {'WON', 'LOST'}
VALID_LOST_REASONS = {'PRICE', 'NO_RESPONSE', 'NOT_INTERESTED', 'JOINED_COMPETITOR', 'TIMING', 'WRONG_NUMBER', 'DUPLICATE', 'OTHER'}

ALLOWED_BULK_MEMBER_FILTER_KEYS = {
    'view',
    'expires_within',
    'expires_month',
    'expires_year',
    'search_id',
    'search_name',
    'search_national_id',
    'search_phone',
    'search_age',
    'search_gender',
    'search_actual_start',
    'search_start_date',
    'search_end_date',
    'search_package',
    'search_fees',
    'search_invitations',
    'search_comment'
}

BULK_MEMBER_VIEWS = {'active', 'expired', 'all'}
BULK_MEMBER_EXPIRES_WITHIN = {7, 14, 30}
BULK_SELECTION_MODES = {'ids', 'filters'}
BULK_DISTRIBUTION_MODES = {'unassigned', 'equal'}

def validate_positive_int_list(val, name, max_items=None):
    if val is None:
        raise ValueError(f"'{name}' is required")
    if not isinstance(val, list):
        raise ValueError(f"'{name}' must be a list")
    if not val:
        raise ValueError(f"'{name}' cannot be empty")
    cleaned = []
    seen = set()
    for x in val:
        if isinstance(x, bool):
            raise ValueError(f"'{name}' must contain positive integers only")
        try:
            x_int = int(x)
        except (ValueError, TypeError):
            raise ValueError(f"'{name}' must contain positive integers only")
        if x_int <= 0:
            raise ValueError(f"'{name}' must contain positive integers only")
        if x_int in seen:
            continue
        seen.add(x_int)
        cleaned.append(x_int)
        if max_items is not None and len(cleaned) > max_items:
            raise ValueError(f"'{name}' cannot exceed {max_items} items")
    return cleaned

def validate_bulk_member_filters(filters):
    if filters is None:
        return {}
    if not isinstance(filters, dict):
        raise ValueError("'filters' must be an object")

    unknown_keys = set(filters.keys()) - ALLOWED_BULK_MEMBER_FILTER_KEYS
    if unknown_keys:
        raise ValueError(f"Unknown filter key(s): {', '.join(sorted(unknown_keys))}")

    normalized = {}

    view = validate_optional_string(filters.get('view'))
    if view:
        view_lower = view.lower().strip()
        if view_lower not in BULK_MEMBER_VIEWS:
            raise ValueError("Invalid member selection view. Allowed: active, expired, all")
        normalized['view'] = view_lower
    else:
        normalized['view'] = 'all'

    expires_within = validate_optional_string(filters.get('expires_within'))
    if expires_within:
        try:
            expires_within_int = int(expires_within)
        except (ValueError, TypeError):
            raise ValueError("expires_within must be one of 7, 14, or 30")
        if expires_within_int not in BULK_MEMBER_EXPIRES_WITHIN:
            raise ValueError("expires_within must be one of 7, 14, or 30")
        normalized['expires_within'] = expires_within_int

    expires_month = validate_optional_string(filters.get('expires_month'))
    if expires_month:
        if isinstance(filters.get('expires_month'), bool):
            raise ValueError("expires_month must be an integer between 1 and 12")
        try:
            expires_month_int = int(expires_month)
        except (ValueError, TypeError):
            raise ValueError("expires_month must be an integer between 1 and 12")
        if expires_month_int < 1 or expires_month_int > 12:
            raise ValueError("expires_month must be an integer between 1 and 12")
        normalized['expires_month'] = expires_month_int

    expires_year = validate_optional_string(filters.get('expires_year'))
    if expires_year:
        if isinstance(filters.get('expires_year'), bool):
            raise ValueError("expires_year must be a four-digit year")
        try:
            expires_year_int = int(expires_year)
        except (ValueError, TypeError):
            raise ValueError("expires_year must be a four-digit year")
        if expires_year_int < 1000 or expires_year_int > 9999:
            raise ValueError("expires_year must be a four-digit year")
        normalized['expires_year'] = expires_year_int

    for key in [
        'search_id',
        'search_name',
        'search_national_id',
        'search_phone',
        'search_age',
        'search_gender',
        'search_actual_start',
        'search_start_date',
        'search_end_date',
        'search_package',
        'search_fees',
        'search_invitations',
        'search_comment'
    ]:
        value = validate_optional_string(filters.get(key))
        if value:
            normalized[key] = value

    return normalized

def validate_bulk_selection_mode(mode):
    if mode is None:
        raise ValueError("'selection.mode' is required")
    mode_str = str(mode).strip().lower()
    if mode_str not in BULK_SELECTION_MODES:
        raise ValueError("Invalid selection mode. Allowed: ids, filters")
    return mode_str

def validate_bulk_distribution_mode(mode):
    if mode is None:
        raise ValueError("'distribution.mode' is required")
    mode_str = str(mode).strip().lower()
    if mode_str not in BULK_DISTRIBUTION_MODES:
        raise ValueError("Invalid distribution mode. Allowed: unassigned, equal")
    return mode_str

def validate_bulk_source(source):
    if source is None:
        raise ValueError("'source' is required")
    source_str = str(source).strip().upper()
    if source_str != 'EXISTING_MEMBER':
        raise ValueError("Bulk member lead creation only supports EXISTING_MEMBER source.")
    return source_str

def validate_stage_transition(old_stage, new_stage):
    old_upper = str(old_stage).upper().strip()
    new_upper = str(new_stage).upper().strip()

    if new_upper == 'WON':
        raise ValueError("WON stage cannot be manually selected.")
    if old_upper == 'WON':
        raise ValueError("Transitions from WON stage are not allowed.")
    if old_upper == new_upper:
        raise ValueError("Stage change must be to a different stage.")
    if old_upper == 'LOST':
        raise ValueError("Stage change from LOST is not allowed through this endpoint. Please use the reopen endpoint.")

    if old_upper in ACTIVE_LEAD_STAGES:
        if new_upper in ACTIVE_LEAD_STAGES or new_upper == 'LOST':
            return new_upper

    raise ValueError(f"Invalid transition from {old_upper} to {new_upper}")

def validate_lost_reason(new_stage, lost_reason):
    new_upper = str(new_stage).upper().strip()
    if new_upper == 'LOST':
        if not lost_reason:
            raise ValueError("Lost reason is required when stage is set to LOST.")
        reason_upper = str(lost_reason).upper().strip()
        if reason_upper not in VALID_LOST_REASONS:
            raise ValueError(f"Invalid lost reason: {lost_reason}. Allowed: {', '.join(VALID_LOST_REASONS)}")
        return reason_upper
    return None

def validate_reopen_stage(stage):
    if not stage:
        return 'FOLLOW_UP'
    stage_upper = str(stage).upper().strip()
    if stage_upper not in ACTIVE_LEAD_STAGES:
        raise ValueError(f"Reopen stage must be one of the active stages: {', '.join(ACTIVE_LEAD_STAGES)}")
    return stage_upper
