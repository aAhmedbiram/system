from psycopg2.extras import Json

from system_app.queries import query_db
from system_app.func import get_cairo_date

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
    """Retrieves a single CRM Lead by its database ID including assigned username."""
    query = """
        SELECT l.*, u.username AS assigned_username
        FROM crm_leads l
        LEFT JOIN users u ON u.id = l.assigned_user_id
        WHERE l.id = %s
    """
    return query_db(query, (lead_id,), one=True)

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

def get_members_by_ids(member_ids):
    """Fetches member rows for a set of member IDs in a single query."""
    if not member_ids:
        return []
    query = """
        SELECT id, name, phone, email, age, gender, birthdate, actual_starting_date,
               starting_date, end_date, membership_packages, membership_fees,
               membership_status, invitations, comment, national_id
        FROM members
        WHERE id = ANY(%s)
        ORDER BY id ASC
    """
    return query_db(query, (member_ids,)) or []

def _build_member_bulk_filter_components(filters):
    """Builds the same member filter semantics used by the filtered members page."""
    from datetime import timedelta

    filters = filters or {}
    where_clauses = []
    args = []

    view = filters.get('view', 'all')
    if view == 'active':
        where_clauses.append("""
            (end_date IS NOT NULL AND end_date != '' AND
             LENGTH(TRIM(end_date)) >= 10 AND
             CASE
                 WHEN SUBSTRING(TRIM(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN
                     CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) >= (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Cairo')::DATE
                 ELSE FALSE
             END)
        """)
    elif view == 'expired':
        where_clauses.append("""
            (end_date IS NOT NULL AND end_date != '' AND
             LENGTH(TRIM(end_date)) >= 10 AND
             CASE
                 WHEN SUBSTRING(TRIM(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN
                     CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) < (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Cairo')::DATE
                 ELSE FALSE
             END)
        """)

    if filters.get('search_id'):
        where_clauses.append("CAST(m.id AS TEXT) ILIKE %s")
        args.append(f"%{filters['search_id']}%")

    if filters.get('search_name'):
        where_clauses.append("name ILIKE %s")
        args.append(f"%{filters['search_name']}%")

    if filters.get('search_national_id'):
        where_clauses.append("COALESCE(national_id, '') ILIKE %s")
        args.append(f"%{filters['search_national_id']}%")

    if filters.get('search_phone'):
        where_clauses.append("COALESCE(phone, '') ILIKE %s")
        args.append(f"%{filters['search_phone']}%")

    if filters.get('search_age'):
        where_clauses.append("CAST(age AS TEXT) ILIKE %s")
        args.append(f"%{filters['search_age']}%")

    if filters.get('search_gender'):
        where_clauses.append("COALESCE(gender, '') ILIKE %s")
        args.append(f"%{filters['search_gender']}%")

    if filters.get('search_actual_start'):
        where_clauses.append("COALESCE(actual_starting_date, '') ILIKE %s")
        args.append(f"%{filters['search_actual_start']}%")

    if filters.get('search_start_date'):
        where_clauses.append("COALESCE(starting_date, '') ILIKE %s")
        args.append(f"%{filters['search_start_date']}%")

    if filters.get('search_end_date'):
        where_clauses.append("COALESCE(end_date, '') ILIKE %s")
        args.append(f"%{filters['search_end_date']}%")

    if filters.get('search_package'):
        where_clauses.append("COALESCE(membership_packages, '') ILIKE %s")
        args.append(f"%{filters['search_package']}%")

    if filters.get('search_fees'):
        where_clauses.append("CAST(membership_fees AS TEXT) ILIKE %s")
        args.append(f"%{filters['search_fees']}%")

    expires_within = filters.get('expires_within')
    if expires_within:
        today = get_cairo_date()
        upper = (today + timedelta(days=expires_within)).strftime('%Y-%m-%d')
        if expires_within == 7:
            where_clauses.append("""
                end_date IS NOT NULL AND end_date != ''
                AND LENGTH(TRIM(end_date)) >= 10
                AND SUBSTRING(TRIM(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) >= (CURRENT_TIMESTAMP AT TIME ZONE 'Africa/Cairo')::DATE
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) <= %s
            """)
            args.append(upper)
        elif expires_within == 14:
            lower = (today + timedelta(days=7)).strftime('%Y-%m-%d')
            where_clauses.append("""
                end_date IS NOT NULL AND end_date != ''
                AND LENGTH(TRIM(end_date)) >= 10
                AND SUBSTRING(TRIM(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) > %s
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) <= %s
            """)
            args.extend([lower, upper])
        elif expires_within == 30:
            lower = (today + timedelta(days=14)).strftime('%Y-%m-%d')
            where_clauses.append("""
                end_date IS NOT NULL AND end_date != ''
                AND LENGTH(TRIM(end_date)) >= 10
                AND SUBSTRING(TRIM(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) > %s
                AND CAST(SUBSTRING(TRIM(end_date), 1, 10) AS DATE) <= %s
            """)
            args.extend([lower, upper])

    if filters.get('search_invitations'):
        where_clauses.append("CAST(COALESCE(invitations, 0) AS TEXT) ILIKE %s")
        args.append(f"%{filters['search_invitations']}%")

    if filters.get('search_comment'):
        where_clauses.append("COALESCE(comment, '') ILIKE %s")
        args.append(f"%{filters['search_comment']}%")

    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    return clause_str, tuple(args)

def _build_member_bulk_filter_query(filters):
    """Builds the same member filter semantics used by the filtered members page."""
    clause_str, args = _build_member_bulk_filter_components(filters)
    query = f"SELECT m.id FROM members m {clause_str} ORDER BY m.id ASC"
    return query, args

def get_member_ids_by_filters(filters):
    """Resolves member IDs for the CRM bulk selection filter semantics."""
    query, args = _build_member_bulk_filter_query(filters)
    rows = query_db(query, args) or []
    return [row['id'] for row in rows]

def get_bulk_member_listing(filters, page, per_page):
    """Returns a paginated CRM bulk-selection member listing with active lead markers."""
    clause_str, args = _build_member_bulk_filter_components(filters)
    offset = (page - 1) * per_page
    count_query = f"SELECT COUNT(*) AS count FROM members m {clause_str}"
    count_row = query_db(count_query, args, one=True)
    total_count = count_row['count'] if count_row else 0

    query = f"""
        SELECT
            m.id,
            m.name,
            m.phone,
            m.membership_packages,
            m.end_date,
            m.membership_status,
            COALESCE(active_lead.id, NULL) AS active_crm_lead_id,
            CASE WHEN active_lead.id IS NULL THEN FALSE ELSE TRUE END AS has_active_crm_lead
        FROM members m
        LEFT JOIN LATERAL (
            SELECT l.id
            FROM crm_leads l
            WHERE l.member_id = m.id
              AND l.member_id IS NOT NULL
              AND l.stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
              AND l.is_archived = FALSE
            ORDER BY l.id ASC
            LIMIT 1
        ) active_lead ON TRUE
        {clause_str}
        ORDER BY m.id ASC
        LIMIT %s OFFSET %s
    """
    rows = query_db(query, args + (per_page, offset)) or []
    return {
        "items": rows,
        "total_count": total_count,
        "total_pages": (total_count + per_page - 1) // per_page if total_count else 1
    }

def get_active_leads_for_member_ids(member_ids):
    """Returns active CRM leads for the given member IDs as a member_id -> lead_id mapping."""
    if not member_ids:
        return []
    query = """
        SELECT member_id, id AS lead_id
        FROM crm_leads
        WHERE member_id = ANY(%s)
          AND member_id IS NOT NULL
          AND stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
          AND is_archived = FALSE
    """
    return query_db(query, (member_ids,)) or []

def create_bulk_lead_operation(token, created_by_user_id, snapshot, expires_at, status='PREVIEW'):
    """Persists a bulk lead preview/execution operation durably."""
    query = """
        INSERT INTO crm_bulk_lead_operations (
            token, created_by_user_id, status, snapshot, created_at, expires_at
        ) VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP, %s)
        RETURNING id
    """
    res = query_db(
        query,
        (token, created_by_user_id, status, Json(snapshot), expires_at),
        one=True,
        commit=True
    )
    return res['id'] if res else None

def get_bulk_lead_operation_by_token(token):
    """Loads a bulk lead operation by its token, including the frozen snapshot."""
    query = """
        SELECT
            id, token, created_by_user_id, status, snapshot,
            created_at, expires_at, started_at, completed_at
        FROM crm_bulk_lead_operations
        WHERE token = %s
        LIMIT 1
    """
    return query_db(query, (token,), one=True)

def claim_bulk_lead_operation(token, created_by_user_id):
    """Atomically claims a PREVIEW bulk operation for execution."""
    query = """
        UPDATE crm_bulk_lead_operations
           SET status = 'EXECUTING',
               started_at = CURRENT_TIMESTAMP
         WHERE token = %s
           AND created_by_user_id = %s
           AND status = 'PREVIEW'
           AND expires_at > CURRENT_TIMESTAMP
     RETURNING
            id, token, created_by_user_id, status, snapshot,
            created_at, expires_at, started_at, completed_at
    """
    return query_db(query, (token, created_by_user_id), one=True, commit=True)

def finalize_bulk_lead_operation(token, created_by_user_id, status, snapshot):
    """Stores the final bulk execution state and summary in the durable operation row."""
    query = """
        UPDATE crm_bulk_lead_operations
           SET status = %s,
               snapshot = %s,
               completed_at = CURRENT_TIMESTAMP
         WHERE token = %s
           AND created_by_user_id = %s
     RETURNING
            id, token, created_by_user_id, status, snapshot,
            created_at, expires_at, started_at, completed_at
    """
    return query_db(query, (status, Json(snapshot), token, created_by_user_id), one=True, commit=True)

def create_existing_member_lead_in_transaction(cur, member_row, source, created_by_user_id, assigned_user_id=None):
    """Inserts a CRM lead linked to an existing member inside an open transaction."""
    query = """
        INSERT INTO crm_leads (
            member_id, name, phone, email, source, stage,
            assigned_user_id, assigned_by_user_id, assigned_at,
            created_by_user_id
        ) VALUES (%s, %s, %s, %s, %s, 'NEW', %s, %s,
                  CASE WHEN %s IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END,
                  %s)
        RETURNING id
    """
    assigned_by_user_id = created_by_user_id if assigned_user_id is not None else None
    cur.execute(
        query,
        (
            member_row.get('id'),
            member_row.get('name'),
            member_row.get('phone'),
            member_row.get('email'),
            source,
            assigned_user_id,
            assigned_by_user_id,
            assigned_user_id,
            created_by_user_id
        )
    )
    return cur.fetchone()['id']

def get_assignable_users_by_ids(user_ids):
    """Fetches assignable users by ID using the same assignable-user rules as the CRM user list."""
    if not user_ids:
        return []
    query = """
        SELECT id, username, email, is_approved
        FROM users
        WHERE id = ANY(%s)
          AND (is_approved = TRUE OR username = 'rino')
        ORDER BY id ASC
    """
    return query_db(query, (user_ids,)) or []

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
    """Fetches a paginated, filtered list of leads including assigned username."""
    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT l.*, u.username AS assigned_username
        FROM crm_leads l
        LEFT JOIN users u ON u.id = l.assigned_user_id
        {clause_str}
        ORDER BY l.created_at DESC, l.id DESC
        LIMIT %s OFFSET %s
    """
    full_args = list(args) + [limit, offset]
    return query_db(query, tuple(full_args)) or []

def count_leads(where_clauses, args):
    """Counts the total leads matching the given filter criteria."""
    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"SELECT COUNT(*) as count FROM crm_leads l {clause_str}"
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

def get_assignable_users():
    """Gets approved users or user 'rino' who can receive lead assignments."""
    query = """
        SELECT id, username, email, is_approved
        FROM users
        WHERE is_approved = TRUE OR username = 'rino'
        ORDER BY username ASC
    """
    return query_db(query) or []

def get_user_by_id(user_id):
    """Gets basic details of a user by ID."""
    return query_db("SELECT id, username, email, is_approved FROM users WHERE id = %s", (user_id,), one=True)

def assign_lead(lead_id, user_id, actor_id):
    """Sets assigned_user_id, assigned_by_user_id, assigned_at on a lead."""
    query = """
        UPDATE crm_leads
        SET assigned_user_id = %s,
            assigned_by_user_id = %s,
            assigned_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """
    query_db(query, (user_id, actor_id, lead_id), commit=True)

def unassign_lead(lead_id, actor_id):
    """Clears assigned_user_id on a lead."""
    query = """
        UPDATE crm_leads
        SET assigned_user_id = NULL,
            assigned_by_user_id = %s,
            assigned_at = CURRENT_TIMESTAMP,
            updated_at = CURRENT_TIMESTAMP
        WHERE id = %s
    """
    query_db(query, (actor_id, lead_id), commit=True)

def create_activity(lead_id, user_id, activity_type, note=None, result=None, old_stage=None, new_stage=None, old_assigned_user_id=None, new_assigned_user_id=None, follow_up_at=None, commit=True):
    """Log an activity record."""
    # Resolve user's username snapshot
    username_snapshot = None
    if user_id:
        u = get_user_by_id(user_id)
        if u:
            username_snapshot = u.get('username')

    query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type, note, result,
            old_stage, new_stage, old_assigned_user_id, new_assigned_user_id, follow_up_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    query_db(query, (lead_id, user_id, username_snapshot, activity_type, note, result,
                     old_stage, new_stage, old_assigned_user_id, new_assigned_user_id, follow_up_at), commit=commit)

def execute_transaction(operations):
    """Runs a batch of (query, args) inside a single transaction."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from system_app.queries import get_connection_pool, get_database_url

    pool = get_connection_pool()
    conn = None
    if pool is None:
        conn = psycopg2.connect(get_database_url())
    else:
        conn = pool.getconn()

    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        results = []
        for query, args in operations:
            cur.execute(query, args)
            query_upper = query.strip().upper()
            if query_upper.startswith('SELECT') or 'RETURNING' in query_upper:
                results.append(cur.fetchall())
            else:
                results.append(None)
        conn.commit()
        return results
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            if pool:
                pool.putconn(conn)
            else:
                conn.close()

def run_in_transaction(callback, *args, **kwargs):
    """Acquires a pooled connection and runs a callback inside a single transaction."""
    import psycopg2
    from psycopg2.extras import RealDictCursor
    from system_app.queries import get_connection_pool, get_database_url

    pool = get_connection_pool()
    conn = None
    if pool is None:
        conn = psycopg2.connect(get_database_url())
    else:
        conn = pool.getconn()

    cur = None
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        result = callback(cur, *args, **kwargs)
        conn.commit()
        return result
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        if cur:
            cur.close()
        if conn:
            if pool:
                pool.putconn(conn)
            else:
                conn.close()

def get_activities(lead_id, limit, offset):
    """Fetches chronological list of activities for a lead."""
    query = """
        SELECT * FROM crm_activities
        WHERE lead_id = %s
        ORDER BY created_at DESC, id DESC
        LIMIT %s OFFSET %s
    """
    return query_db(query, (lead_id, limit, offset)) or []

def count_activities(lead_id):
    """Counts total activity timeline items for a lead."""
    res = query_db("SELECT COUNT(*) as count FROM crm_activities WHERE lead_id = %s", (lead_id,), one=True)
    return res['count'] if res else 0

def get_follow_up_leads(where_clauses, args, limit, offset, order_by_clause):
    """Retrieves lead records that have pending follow-up schedules."""
    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT id, member_id, name, phone, email, source, stage,
               assigned_user_id, next_follow_up_at, is_archived
        FROM crm_leads
        {where_str}
        ORDER BY {order_by_clause}
        LIMIT %s OFFSET %s
    """
    full_args = list(args) + [limit, offset]
    return query_db(query, tuple(full_args)) or []

def count_follow_up_leads(where_clauses, args):
    """Counts total lead records that match follow-up filters."""
    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"SELECT COUNT(*) as count FROM crm_leads {where_str}"
    res = query_db(query, tuple(args), one=True)
    return res['count'] if res else 0

def get_pipeline_stage_counts(where_clauses, args):
    """Aggregates active lead stage counts respecting access restrictions."""
    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT stage, COUNT(*) as count
        FROM crm_leads
        {where_str}
        GROUP BY stage
    """
    return query_db(query, tuple(args)) or []

def get_lead_by_id_for_update(cur, lead_id):
    """Fetches a lead record and locks it exclusively using FOR UPDATE inside a transaction cursor."""
    cur.execute("SELECT * FROM crm_leads WHERE id = %s FOR UPDATE", (lead_id,))
    return cur.fetchone()

def get_follow_up_summary_counts(where_clauses, args, now_cairo, today_start, today_end):
    """Fetches summary counts of overdue, today, and upcoming follow-ups in a single aggregate query.
    Note: The overdue dashboard count checks against today_start to guarantee mutually exclusive buckets.
    """
    clause_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT
            COUNT(*) FILTER (WHERE l.next_follow_up_at < %s) AS overdue,
            COUNT(*) FILTER (WHERE l.next_follow_up_at >= %s AND l.next_follow_up_at < %s) AS today,
            COUNT(*) FILTER (WHERE l.next_follow_up_at >= %s) AS upcoming
        FROM crm_leads l
        {clause_str}
    """
    full_args = [today_start, today_start, today_end, today_end] + list(args)
    res = query_db(query, tuple(full_args), one=True)
    return {
        "overdue": res["overdue"] if res else 0,
        "today": res["today"] if res else 0,
        "upcoming": res["upcoming"] if res else 0
    }
