from system_app.queries import query_db

def create_lead(member_id, name, phone, email, source, notes, created_by_user_id):
    """Inserts a new CRM Lead into the database and returns the generated ID."""
    query = """
        INSERT INTO crm_leads (
            member_id, name, phone, email, source, stage, notes, created_by_user_id
        ) VALUES (%s, %s, %s, %s, %s, 'NEW', %s, %s)
        RETURNING id
    """
    res = query_db(query, (member_id, name, phone, email, source, notes, created_by_user_id), one=True, commit=True)
    return res['id'] if res else None

def get_lead_by_id(lead_id):
    """Retrieves a single CRM Lead by its database ID."""
    return query_db("SELECT * FROM crm_leads WHERE id = %s", (lead_id,), one=True)

def update_lead(lead_id, **kwargs):
    """Updates selected whitelist fields on a CRM Lead."""
    if not kwargs:
        return False

    # We must construct dynamic parameterized update statement
    set_clause = []
    args = []
    for k, v in kwargs.items():
        set_clause.append(f"{k} = %s")
        args.append(v)

    args.append(lead_id)
    query = f"UPDATE crm_leads SET {', '.join(set_clause)}, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    query_db(query, tuple(args), commit=True)
    return True

def archive_lead(lead_id):
    """Soft-archives a CRM lead by setting is_archived to TRUE."""
    query = "UPDATE crm_leads SET is_archived = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    query_db(query, (lead_id,), commit=True)
    return True

def find_active_lead_by_member(member_id):
    """Checks if there is an active lead linked to the given member ID."""
    query = """
        SELECT id FROM crm_leads
        WHERE member_id = %s
          AND stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
          AND is_archived = FALSE
        LIMIT 1
    """
    return query_db(query, (member_id,), one=True)

def find_active_lead_by_phone(phone):
    """Checks if there is an active prospect lead with the given phone number."""
    query = """
        SELECT id FROM crm_leads
        WHERE phone = %s
          AND member_id IS NULL
          AND stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
          AND is_archived = FALSE
        LIMIT 1
    """
    return query_db(query, (phone,), one=True)

def find_member_matches(phone, email):
    """Searches for existing members matching the phone or email to prevent duplicate prospect entry."""
    query = """
        SELECT id, name, phone, email, membership_status, end_date
        FROM members
        WHERE phone = %s OR (email IS NOT NULL AND email <> '' AND email = %s)
    """
    return query_db(query, (phone, email)) or []

def search_members(search_query, limit=20):
    """Searches members for linking to CRM leads."""
    query = """
        SELECT id, name, phone, email, membership_status, end_date
        FROM members
        WHERE name ILIKE %s
           OR phone ILIKE %s
           OR email ILIKE %s
           OR CAST(id AS TEXT) LIKE %s
        ORDER BY name ASC
        LIMIT %s
    """
    term = f"%{search_query}%"
    return query_db(query, (term, term, term, f"{search_query}%", limit)) or []

def get_leads(where_clauses, args, limit, offset):
    """Fetches a paginated, filtered list of leads."""
    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT * FROM crm_leads
        {clause_str}
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
    """
    full_args = list(args) + [limit, offset]
    return query_db(query, tuple(full_args)) or []

def count_leads(where_clauses, args):
    """Counts the total leads matching the given filter criteria."""
    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"SELECT COUNT(*) as count FROM crm_leads {clause_str}"
    res = query_db(query, tuple(args), one=True)
    return res['count'] if res else 0

def get_crm_counts():
    """Returns basic counts of leads, activities, and campaigns to prove DB reachability."""
    try:
        leads_count = query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)
        activities_count = query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)
        campaigns_count = query_db("SELECT COUNT(*) as count FROM crm_campaigns", one=True)
        return {
            "leads": leads_count["count"] if leads_count else 0,
            "activities": activities_count["count"] if activities_count else 0,
            "campaigns": campaigns_count["count"] if campaigns_count else 0
        }
    except Exception as e:
        print(f"Error checking CRM counts: {e}")
        return None

def crm_schema_health_check():
    """Validates if all three CRM tables exist and can be queried."""
    health = {}
    for table in ["crm_campaigns", "crm_leads", "crm_activities"]:
        try:
            query_db(f"SELECT 1 FROM {table} LIMIT 1")
            health[table] = True
        except Exception:
            health[table] = False
    return health
