from system_app.queries import get_member
from system_app.crm.permissions import can_view_all_leads
from system_app.crm.validators import (
    validate_required_string, validate_optional_string, validate_email,
    validate_positive_int, validate_pagination, validate_stage_filter,
    validate_member_status_filter
)
from system_app.crm import queries

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
