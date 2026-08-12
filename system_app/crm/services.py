from system_app.queries import get_member
from system_app.crm.permissions import can_view_all_leads
from system_app.crm.validators import (
    validate_required_string, validate_optional_string, validate_email,
    validate_positive_int, validate_pagination, validate_stage_filter,
    validate_member_status_filter, validate_user_activity_type,
    validate_iso_timestamp, validate_future_timestamp,
    validate_stage_transition, validate_lost_reason, validate_reopen_stage
)
from system_app.crm import queries
from system_app.crm.queries import run_in_transaction
from system_app.member_services import create_member_in_transaction, renew_member_in_transaction, DuplicateMemberError
from zoneinfo import ZoneInfo

CAIRO_TZ = ZoneInfo("Africa/Cairo")

class CRMConflictError(Exception):
    def __init__(self, error_code, message, details=None):
        super().__init__(message)
        self.error_code = error_code
        self.details = details or {}

class CRMForbiddenError(Exception):
    pass

class CRMNotFoundError(Exception):
    pass

class CRMProtectedFieldError(Exception):
    def __init__(self, fields):
        super().__init__(f"Protected fields cannot be updated: {', '.join(fields)}")
        self.fields = fields

def create_lead(current_user, data):
    """Enforces business rules and inserts a new CRM Lead."""
    created_by_user_id = current_user['id']

    # 1. Parse/validate inputs
    member_id = validate_positive_int(data.get('member_id'), 'member_id')
    source = validate_required_string(data.get('source'), 'source')
    notes = validate_optional_string(data.get('notes'))

    if member_id is not None:
        # EXISTING MEMBER LEAD
        # Verify member exists
        member = get_member(member_id)
        if not member:
            raise ValueError(f"Member with ID {member_id} does not exist")

        # Snapshot member details (Authoritative)
        name = member.get('name')
        phone = member.get('phone')
        email = member.get('email')

        # Check active duplicate lead rule
        active_lead = queries.find_active_lead_by_member(member_id)
        if active_lead:
            raise CRMConflictError(
                "active_lead_exists",
                "An active lead already exists for this member.",
                {"existing_lead_id": active_lead['id']}
            )
    else:
        # NEW PROSPECT
        name = validate_required_string(data.get('name'), 'name')
        phone = validate_required_string(data.get('phone'), 'phone')
        email = validate_email(data.get('email'))

        # Check member already in system detection
        member_matches = queries.find_member_matches(phone, email)
        if member_matches:
            # We return conflict list suggesting link
            matches_details = [
                {
                    "id": m['id'],
                    "name": m['name'],
                    "phone": m['phone'],
                    "email": m['email']
                }
                for m in member_matches
            ]
            raise CRMConflictError(
                "member_match_found",
                "Existing member records match this phone or email.",
                {"members": matches_details}
            )

        # Check active duplicate lead rule for prospect phone
        active_lead = queries.find_active_lead_by_phone(phone)
        if active_lead:
            raise CRMConflictError(
                "active_lead_exists",
                "An active lead already exists for this phone number.",
                {"existing_lead_id": active_lead['id']}
            )

    # Write to database
    lead_id = queries.create_lead(member_id, name, phone, email, source, notes, created_by_user_id)
    return lead_id

def check_lead_visibility(current_user, lead):
    """Enforces visibility check. True if user has rights, False otherwise."""
    if not lead:
        return False
    if can_view_all_leads(current_user):
        return True

    # Regular user check
    if lead.get('assigned_user_id') == current_user['id']:
        return True
    if lead.get('created_by_user_id') == current_user['id'] and lead.get('assigned_user_id') is None:
        return True

    return False

def list_leads(current_user, page_param, per_page_param, filters):
    """Lists leads enforcing visibility logic, searches, and pagination."""
    page, per_page = validate_pagination(page_param, per_page_param)
    offset = (page - 1) * per_page

    where_clauses = ["is_archived = FALSE"]
    args = []

    # 1. Enforce visibility rules
    if not can_view_all_leads(current_user):
        where_clauses.append("(assigned_user_id = %s OR (created_by_user_id = %s AND assigned_user_id IS NULL))")
        args.append(current_user['id'])
        args.append(current_user['id'])

    # 2. Apply filters
    stage_filter = validate_stage_filter(filters.get('stage'))
    if stage_filter:
        where_clauses.append("stage = %s")
        args.append(stage_filter)

    source_filter = validate_optional_string(filters.get('source'))
    if source_filter:
        where_clauses.append("source = %s")
        args.append(source_filter)

    m_status = validate_member_status_filter(filters.get('member_status'))
    if m_status == 'member':
        where_clauses.append("member_id IS NOT NULL")
    elif m_status == 'prospect':
        where_clauses.append("member_id IS NULL")

    search_q = validate_optional_string(filters.get('search'))
    if search_q:
        if search_q.isdigit():
            where_clauses.append("(name ILIKE %s OR phone ILIKE %s OR email ILIKE %s OR member_id = %s)")
            term = f"%{search_q}%"
            args.extend([term, term, term, int(search_q)])
        else:
            where_clauses.append("(name ILIKE %s OR phone ILIKE %s OR email ILIKE %s)")
            term = f"%{search_q}%"
            args.extend([term, term, term])

    # Fetch results
    items = queries.get_leads(where_clauses, args, per_page, offset)
    total = queries.count_leads(where_clauses, args)

    # Calculate pages
    pages = (total + per_page - 1) // per_page if total > 0 else 1

    return {
        "items": items,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages
    }

def get_lead(current_user, lead_id):
    """Retrieves a single lead, mapping nested member if linked and checking auth."""
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")

    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to view this lead")

    lead_dict = dict(lead)
    lead_dict['is_existing_member'] = lead_dict['member_id'] is not None

    if lead_dict['member_id'] is not None:
        member = get_member(lead_dict['member_id'])
        if member:
            lead_dict['member'] = {
                "id": member.get('id'),
                "name": member.get('name'),
                "phone": member.get('phone'),
                "membership_status": member.get('membership_status'),
                "end_date": member.get('end_date')
            }

    return lead_dict

def update_lead(current_user, lead_id, data):
    """Updates whitelist fields on lead."""
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")

    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to modify this lead")

    # Check for protected fields
    protected_fields = [
        'member_id', 'stage', 'assigned_user_id', 'assigned_by_user_id',
        'assigned_at', 'campaign_id', 'next_follow_up_at', 'lost_reason',
        'created_by_user_id', 'created_at', 'converted_by_user_id',
        'converted_at', 'is_archived'
    ]
    invalid_fields = [f for f in data.keys() if f in protected_fields]
    if invalid_fields:
        raise CRMProtectedFieldError(invalid_fields)

    # Whitelist filters
    update_data = {}
    if 'name' in data:
        update_data['name'] = validate_required_string(data['name'], 'name')
    if 'phone' in data:
        update_data['phone'] = validate_required_string(data['phone'], 'phone')
    if 'email' in data:
        update_data['email'] = validate_email(data['email'])
    if 'source' in data:
        update_data['source'] = validate_required_string(data['source'], 'source')
    if 'notes' in data:
        update_data['notes'] = validate_optional_string(data['notes'])

    if update_data:
        queries.update_lead(lead_id, **update_data)
    return True

def archive_lead(current_user, lead_id):
    """Archives lead, verifying visibility."""
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")

    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to archive this lead")

    queries.archive_lead(lead_id)
    return True

def search_existing_members(current_user, query_str):
    """Allows searching existing members database."""
    query = validate_required_string(query_str, 'q')
    return queries.search_members(query)

def get_crm_health():
    """Runs a health check on all CRM tables and returns module operational status."""
    table_health = queries.crm_schema_health_check()
    all_ok = all(table_health.values())
    return {
        "status": "ok" if all_ok else "degraded",
        "module": "crm",
        "tables": table_health
    }

def get_crm_home_summary():
    """Returns static summary attributes for the root placeholder response."""
    db_counts = queries.get_crm_counts()
    return {
        "module": "crm",
        "status": "ready",
        "phase": "1B",
        "database_metrics": db_counts
    }

def list_assignable_users(current_user):
    """Lists approved assignment targets."""
    return queries.get_assignable_users()

def assign_lead(current_user, lead_id, target_user_id):
    """Assigns or reassigns a single lead to a target user."""
    # 1. Validate lead exists and is not archived
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")
    if lead.get('is_archived'):
        raise CRMConflictError("lead_archived", "Archived leads cannot be assigned.")

    # 2. Validate target user exists and is approved (unless Rino)
    target_user = queries.get_user_by_id(target_user_id)
    if not target_user:
        raise CRMNotFoundError("user_not_found", "Assignment target user does not exist.")
    if target_user.get('username') != 'rino' and not target_user.get('is_approved'):
        raise CRMConflictError("user_not_approved", "Lead cannot be assigned to an unapproved user.")

    # 3. Perform update and log activity in a transaction
    previous_assigned_user_id = lead.get('assigned_user_id')

    lead_query = """
        UPDATE crm_leads
        SET assigned_user_id = %s,
            assigned_by_user_id = %s,
            assigned_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """

    activity_query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type,
            old_assigned_user_id, new_assigned_user_id
        ) VALUES (%s, %s, %s, 'ASSIGNED', %s, %s)
    """

    operations = [
        (lead_query, (target_user_id, current_user['id'], lead_id)),
        (activity_query, (lead_id, current_user['id'], current_user.get('username'), previous_assigned_user_id, target_user_id))
    ]

    queries.execute_transaction(operations)
    return True

def unassign_lead(current_user, lead_id):
    """Unassigns a lead, clearing the assignee."""
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")
    if lead.get('is_archived'):
        raise CRMConflictError("lead_archived", "Archived leads cannot be assigned.")

    previous_assigned_user_id = lead.get('assigned_user_id')

    lead_query = """
        UPDATE crm_leads
        SET assigned_user_id = NULL,
            assigned_by_user_id = %s,
            assigned_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """

    activity_query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type,
            old_assigned_user_id, new_assigned_user_id
        ) VALUES (%s, %s, %s, 'ASSIGNED', %s, %s)
    """

    operations = [
        (lead_query, (current_user['id'], lead_id)),
        (activity_query, (lead_id, current_user['id'], current_user.get('username'), previous_assigned_user_id, None))
    ]

    queries.execute_transaction(operations)
    return True

def bulk_assign_leads(current_user, lead_ids_raw, target_user_id):
    """Bulk assigns multiple leads to a user inside a single database transaction."""
    from system_app.crm.validators import validate_integer_list

    lead_ids = validate_integer_list(lead_ids_raw, 'lead_ids')
    # Remove duplicates
    lead_ids = list(dict.fromkeys(lead_ids))

    # 1. Validate target user
    target_user = queries.get_user_by_id(target_user_id)
    if not target_user:
        raise CRMNotFoundError("user_not_found", "Assignment target user does not exist.")
    if target_user.get('username') != 'rino' and not target_user.get('is_approved'):
        raise CRMConflictError("user_not_approved", "Lead cannot be assigned to an unapproved user.")

    # 2. Fetch and validate all leads before updating
    invalid_lead_ids = []
    leads_to_assign = []

    for lid in lead_ids:
        lead = queries.get_lead_by_id(lid)
        if not lead or lead.get('is_archived'):
            invalid_lead_ids.append(lid)
        else:
            leads_to_assign.append(lead)

    if invalid_lead_ids:
        raise CRMConflictError(
            "bulk_assignment_failed",
            "One or more leads do not exist or are archived.",
            {"invalid_lead_ids": sorted(invalid_lead_ids)}
        )

    # 3. Build transactional operations list
    operations = []
    for lead in leads_to_assign:
        # Update lead operations
        lead_query = """
            UPDATE crm_leads
            SET assigned_user_id = %s,
                assigned_by_user_id = %s,
                assigned_at = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        operations.append((lead_query, (target_user_id, current_user['id'], lead['id'])))

        # Insert activity operations
        username_snapshot = current_user.get('username')
        activity_query = """
            INSERT INTO crm_activities (
                lead_id, user_id, user_username_snapshot, activity_type,
                old_assigned_user_id, new_assigned_user_id
            ) VALUES (%s, %s, %s, 'ASSIGNED', %s, %s)
        """
        operations.append((activity_query, (lead['id'], current_user['id'], username_snapshot, lead.get('assigned_user_id'), target_user_id)))

    if operations:
        queries.execute_transaction(operations)
    return True

def add_activity(current_user, lead_id, data):
    """Creates a new timeline activity record and atomically manages follow-up scheduling."""
    # 1. Fetch and validate lead
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")
    if lead.get('is_archived'):
        raise CRMConflictError("lead_archived", "Archived leads cannot receive new activities.")

    # 2. Check visibility
    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to view or edit this lead")

    # 3. Parse and validate parameters
    activity_type = validate_user_activity_type(data.get('activity_type'))
    note = validate_optional_string(data.get('note'))
    result = validate_optional_string(data.get('result'))

    # Check follow-up field semantics
    # We check if key exists in dictionary to distinguish omitted vs explicit null
    has_follow_up_key = 'next_follow_up_at' in data
    follow_up_dt = None

    if has_follow_up_key:
        raw_val = data.get('next_follow_up_at')
        if raw_val is not None:
            # Timestamp provided
            follow_up_dt = validate_iso_timestamp(raw_val)
            validate_future_timestamp(follow_up_dt)
        else:
            # Explicit null: clear follow-up and mark activity record as cleared
            if result:
                result = f"{result} [FOLLOW_UP_CLEARED]"
            else:
                result = "FOLLOW_UP_CLEARED"

    # Business constraint rule for FOLLOW_UP type: requires note or timestamp
    if activity_type == 'FOLLOW_UP':
        if not note and (not has_follow_up_key or data.get('next_follow_up_at') is None):
            raise ValueError("FOLLOW_UP activity requires either a note or a scheduled follow-up time.")

    # 4. Prepare database transactional statements
    operations = []

    # A. Insert Activity
    username_snapshot = current_user.get('username')
    activity_query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type,
            note, result, follow_up_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
    """
    operations.append((activity_query, (lead_id, current_user['id'], username_snapshot, activity_type, note, result, follow_up_dt)))

    # B. Update Lead next_follow_up_at if follow-up key is present
    if has_follow_up_key:
        lead_update_query = """
            UPDATE crm_leads
            SET next_follow_up_at = %s,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        operations.append((lead_update_query, (follow_up_dt, lead_id)))

    # Run atomically
    queries.execute_transaction(operations)
    return True

def list_activities(current_user, lead_id, page_param, per_page_param):
    """Retrieves chronological activity log timeline for an authorized user."""
    # 1. Fetch and validate lead
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")

    # 2. Check visibility
    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to view this lead's activities")

    # 3. Paginate
    page, per_page = validate_pagination(page_param, per_page_param)
    offset = (page - 1) * per_page

    # Fetch
    items = queries.get_activities(lead_id, per_page, offset)
    total = queries.count_activities(lead_id)
    pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Serialize items safely converting datetime objects to strings if needed
    serialized = []
    for item in items:
        serialized.append(dict(item))

    return {
        "items": serialized,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages
    }

def list_follow_ups(current_user, page_param, per_page_param, filters):
    """Lists leads scheduled for follow-up, sorted and timezone-filtered."""
    page, per_page = validate_pagination(page_param, per_page_param)
    offset = (page - 1) * per_page

    # Active stage constraint: NEW, CONTACTED, FOLLOW_UP, INTERESTED, TRIAL (non-terminal)
    where_clauses = [
        "is_archived = FALSE",
        "stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')",
        "next_follow_up_at IS NOT NULL"
    ]
    args = []

    # 1. Enforce visibility rules
    if not can_view_all_leads(current_user):
        where_clauses.append("(assigned_user_id = %s OR (created_by_user_id = %s AND assigned_user_id IS NULL))")
        args.extend([current_user['id'], current_user['id']])

    # 2. Cairo calendar day computations using ZoneInfo("Africa/Cairo")
    import datetime
    now_cairo = datetime.datetime.now(CAIRO_TZ)
    today_start = now_cairo.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + datetime.timedelta(days=1)

    # 3. Filter statuses
    status_filter = filters.get('status')
    order_by = "next_follow_up_at ASC"  # Default ordering

    if status_filter == 'today':
        where_clauses.append("next_follow_up_at >= %s AND next_follow_up_at < %s")
        args.extend([today_start, today_end])
    elif status_filter == 'overdue':
        where_clauses.append("next_follow_up_at < %s")
        args.append(now_cairo)
    elif status_filter == 'upcoming':
        where_clauses.append("next_follow_up_at >= %s")
        args.append(today_end)

    # Fetch
    items = queries.get_follow_up_leads(where_clauses, args, per_page, offset, order_by)
    total = queries.count_follow_up_leads(where_clauses, args)
    pages = (total + per_page - 1) // per_page if total > 0 else 1

    # Map items to include is_existing_member flag
    serialized = []
    for item in items:
        lead_dict = dict(item)
        lead_dict['is_existing_member'] = lead_dict['member_id'] is not None
        serialized.append(lead_dict)

    return {
        "items": serialized,
        "page": page,
        "per_page": per_page,
        "total": total,
        "pages": pages
    }

def change_lead_stage(current_user, lead_id, data):
    """Updates a lead's sales pipeline stage and logs a STAGE_CHANGE activity record."""
    # 1. Fetch and validate lead
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")
    if lead.get('is_archived'):
        raise CRMConflictError("lead_archived", "Archived leads cannot change stage.")

    # 2. Check visibility
    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to view or edit this lead")

    # 3. Validate transition
    old_stage = lead['stage']
    new_stage = validate_stage_transition(old_stage, data.get('stage'))
    lost_reason = validate_lost_reason(new_stage, data.get('lost_reason'))

    # 4. Prepare transactional queries
    operations = []

    # Update lead stage
    # If moving to LOST, clear next_follow_up_at automatically
    if new_stage == 'LOST':
        lead_query = """
            UPDATE crm_leads
            SET stage = %s,
                lost_reason = %s,
                next_follow_up_at = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        lead_args = (new_stage, lost_reason, lead_id)
    else:
        lead_query = """
            UPDATE crm_leads
            SET stage = %s,
                lost_reason = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        """
        lead_args = (new_stage, lead_id)

    operations.append((lead_query, lead_args))

    # Log STAGE_CHANGE activity
    username_snapshot = current_user.get('username')
    activity_query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type,
            old_stage, new_stage, result
        ) VALUES (%s, %s, %s, 'STAGE_CHANGE', %s, %s, %s)
    """
    operations.append((activity_query, (lead_id, current_user['id'], username_snapshot, old_stage, new_stage, lost_reason)))

    queries.execute_transaction(operations)
    return {
        "status": "updated",
        "lead_id": lead_id,
        "old_stage": old_stage,
        "new_stage": new_stage,
        "lost_reason": lost_reason
    }

def reopen_lead(current_user, lead_id, data):
    """Reopens a LOST lead, moving it back to an active stage and logging a REOPENED activity."""
    # 1. Fetch and validate lead
    lead = queries.get_lead_by_id(lead_id)
    if not lead:
        raise CRMNotFoundError("Lead not found")
    if lead.get('is_archived'):
        raise CRMConflictError("lead_archived", "Archived leads cannot be reopened.")

    # 2. Check visibility
    if not check_lead_visibility(current_user, lead):
        raise CRMForbiddenError("You are not authorized to view or edit this lead")

    # 3. Validate current state and target stage
    old_stage = lead['stage']
    if old_stage != 'LOST':
        raise CRMConflictError("lead_not_lost", f"Only LOST leads can be reopened. Current stage: {old_stage}")

    new_stage = validate_reopen_stage(data.get('stage'))

    # 4. Prepare transactional queries
    operations = []

    # Update lead stage, clearing lost_reason (next_follow_up_at remains NULL until scheduled)
    lead_query = """
        UPDATE crm_leads
        SET stage = %s,
            lost_reason = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """
    operations.append((lead_query, (new_stage, lead_id)))

    # Log REOPENED activity
    username_snapshot = current_user.get('username')
    activity_query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type,
            old_stage, new_stage
        ) VALUES (%s, %s, %s, 'REOPENED', %s, %s)
    """
    operations.append((activity_query, (lead_id, current_user['id'], username_snapshot, old_stage, new_stage)))

    queries.execute_transaction(operations)
    return {
        "status": "updated",
        "lead_id": lead_id,
        "old_stage": old_stage,
        "new_stage": new_stage
    }

def get_pipeline_summary(current_user):
    """Aggregates leads counts across all valid crm stages respecting access controls."""
    where_clauses = ["is_archived = FALSE"]
    args = []

    # 1. Enforce visibility constraints
    if not can_view_all_leads(current_user):
        where_clauses.append("(assigned_user_id = %s OR (created_by_user_id = %s AND assigned_user_id IS NULL))")
        args.extend([current_user['id'], current_user['id']])

    # 2. Fetch counts
    rows = queries.get_pipeline_stage_counts(where_clauses, args)

    # 3. Initialize mapping for all stages to 0
    from system_app.crm.validators import VALID_LEAD_STAGES
    summary = {stage: 0 for stage in VALID_LEAD_STAGES}
    for row in rows:
        summary[row['stage']] = row['count']

    return summary

def convert_lead(current_user, lead_id, data):
    """Converts a prospect or reactivates an existing member lead atomically inside a locked transaction."""
    def callback(cur):
        # 1. Fetch lead and lock row FOR UPDATE
        lead = queries.get_lead_by_id_for_update(cur, lead_id)
        if not lead:
            raise CRMNotFoundError("Lead not found")

        # 2. Revalidate state after lock
        if lead.get('is_archived'):
            raise CRMConflictError("lead_archived", "Archived leads cannot be converted.")
        if lead.get('stage') == 'WON' or lead.get('converted_at') is not None:
            raise CRMConflictError("already_converted", "This lead is already converted.")
        if lead.get('stage') == 'LOST':
            raise CRMConflictError("lead_lost", "LOST leads cannot be directly converted. Please reopen them first.")

        # 3. Check Visibility
        if not check_lead_visibility(current_user, lead):
            raise CRMForbiddenError("You are not authorized to convert this lead.")

        username = current_user.get('username', 'Unknown')

        # Branch Case A / Case B
        if lead.get('member_id') is None:
            # CASE A: New Prospect
            member_data = {
                "name": lead['name'],
                "phone": lead['phone'],
                "email": lead.get('email'),
                "gender": data.get('gender'),
                "birthdate": data.get('birthdate'),
                "starting_date": data.get('starting_date'),
                "actual_starting_date": data.get('actual_starting_date'),
                "membership_packages": data.get('membership_packages'),
                "membership_fees": data.get('membership_fees'),
                "comment": data.get('comment'),
                "national_id": data.get('national_id')
            }
            import psycopg2
            try:
                res = create_member_in_transaction(cur, member_data, username)
            except DuplicateMemberError as e:
                raise CRMConflictError("duplicate_member", str(e))
            except ValueError as e:
                raise e
            except psycopg2.IntegrityError as e:
                if hasattr(e, 'pgcode') and e.pgcode == '23505':
                    raise CRMConflictError("duplicate_member", "A member with this phone or national ID already exists.")
                raise e

            member_id = res['member_id']
            invoice_id = res['invoice_id']
            invoice_number = res['invoice_number']

            # Update CRM Lead
            query_update = """
                UPDATE crm_leads
                SET member_id = %s,
                    stage = 'WON',
                    converted_by_user_id = %s,
                    converted_at = CURRENT_TIMESTAMP,
                    next_follow_up_at = NULL,
                    lost_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """
            cur.execute(query_update, (member_id, current_user['id'], lead_id))

            # Log CRM Activity
            query_act = """
                INSERT INTO crm_activities (
                    lead_id, user_id, user_username_snapshot, activity_type,
                    old_stage, new_stage, result, note
                ) VALUES (%s, %s, %s, 'CONVERTED', %s, 'WON', 'NEW_MEMBER', %s);
            """
            note_str = f"Converted to member ID: {member_id}"
            cur.execute(query_act, (lead_id, current_user['id'], username, lead['stage'], note_str))

            return {
                "status": "converted",
                "conversion_type": "new_member",
                "lead_id": lead_id,
                "member_id": member_id,
                "stage": "WON",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number
            }
        else:
            # CASE B: Existing Member Reactivation
            member_id = lead['member_id']
            renew_data = {
                "starting_date": data.get('starting_date'),
                "membership_packages": data.get('membership_packages'),
                "membership_fees": data.get('membership_fees')
            }
            try:
                res = renew_member_in_transaction(cur, member_id, renew_data, username)
            except ValueError as e:
                raise CRMConflictError("reactivation_failed", str(e))

            invoice_id = res['invoice_id']
            invoice_number = res['invoice_number']

            # Update CRM Lead
            query_update = """
                UPDATE crm_leads
                SET stage = 'WON',
                    converted_by_user_id = %s,
                    converted_at = CURRENT_TIMESTAMP,
                    next_follow_up_at = NULL,
                    lost_reason = NULL,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s;
            """
            cur.execute(query_update, (current_user['id'], lead_id))

            # Log CRM Activity
            query_act = """
                INSERT INTO crm_activities (
                    lead_id, user_id, user_username_snapshot, activity_type,
                    old_stage, new_stage, result
                ) VALUES (%s, %s, %s, 'REACTIVATED', %s, 'WON', 'REACTIVATION');
            """
            cur.execute(query_act, (lead_id, current_user['id'], username, lead['stage']))

            return {
                "status": "converted",
                "conversion_type": "reactivation",
                "lead_id": lead_id,
                "member_id": member_id,
                "stage": "WON",
                "invoice_id": invoice_id,
                "invoice_number": invoice_number
            }

    return run_in_transaction(callback)
