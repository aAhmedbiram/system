import re
from datetime import date, datetime, time

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

def create_campaign(name, description, created_by_user_id, is_active=True):
    """Creates a CRM campaign/cycle row and returns its generated ID."""
    query = """
        INSERT INTO crm_campaigns (
            name, description, created_by_user_id, is_active
        ) VALUES (%s, %s, %s, %s)
        RETURNING id
    """
    res = query_db(query, (name, description, created_by_user_id, is_active), one=True, commit=True)
    return res['id'] if res else None

def _json_safe_value(value):
    """Converts DB values into JSON-safe primitives without mutating row objects."""
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe_value(item) for item in value]
    return value

def _json_safe_row(row):
    if row is None:
        return None
    return {key: _json_safe_value(value) for key, value in dict(row).items()}

_INVITATION_PHONE_PATTERN = re.compile(r"^01[0125][0-9]{8}$")

def get_lead_by_id(lead_id):
    """Retrieves a single CRM Lead by its database ID including assigned username."""
    query = """
        SELECT l.*, u.username AS assigned_username, c.name AS campaign_name
        FROM crm_leads l
        LEFT JOIN users u ON u.id = l.assigned_user_id
        LEFT JOIN crm_campaigns c ON c.id = l.campaign_id
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
    end_date_text = "TRIM(end_date)"
    end_date_prefix = f"SUBSTRING({end_date_text}, 1, 10)"
    valid_end_date_clause = f"{end_date_prefix} ~ '^[0-9]{{4}}-[0-9]{{2}}-[0-9]{{2}}$'"
    end_date_date_expr = f"CAST({end_date_prefix} AS DATE)"

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

    expires_month = filters.get('expires_month')
    if expires_month:
        where_clauses.append(f"""
            end_date IS NOT NULL AND end_date != ''
            AND LENGTH({end_date_text}) >= 10
            AND {valid_end_date_clause}
            AND EXTRACT(MONTH FROM {end_date_date_expr}) = %s
        """)
        args.append(expires_month)

    expires_year = filters.get('expires_year')
    if expires_year:
        where_clauses.append(f"""
            end_date IS NOT NULL AND end_date != ''
            AND LENGTH({end_date_text}) >= 10
            AND {valid_end_date_clause}
            AND EXTRACT(YEAR FROM {end_date_date_expr}) = %s
        """)
        args.append(expires_year)

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

def _build_invitation_candidate_filter_components(filters):
    """Builds invitation intake filters for recurring CRM bulk lead ingestion."""
    filters = filters or {}
    where_clauses = []
    args = []

    search_name = filters.get('search_name')
    if search_name:
        where_clauses.append("TRIM(COALESCE(i.friend_name, '')) ILIKE %s")
        args.append(f"%{search_name}%")

    search_phone = filters.get('search_phone')
    if search_phone:
        where_clauses.append("TRIM(COALESCE(i.friend_phone, '')) ILIKE %s")
        args.append(f"%{search_phone}%")

    used_by = filters.get('used_by')
    if used_by:
        where_clauses.append("TRIM(COALESCE(i.used_by, '')) = %s")
        args.append(used_by)

    invitation_month = filters.get('invitation_month')
    if invitation_month is not None:
        where_clauses.append("EXTRACT(MONTH FROM i.used_date) = %s")
        args.append(invitation_month)

    invitation_year = filters.get('invitation_year')
    if invitation_year is not None:
        where_clauses.append("EXTRACT(YEAR FROM i.used_date) = %s")
        args.append(invitation_year)

    clause_str = f"AND {' AND '.join(where_clauses)}" if where_clauses else ""
    return clause_str, tuple(args)

def _build_invitation_candidate_sql(filters, candidate_keys=None):
    """Builds the shared invitation candidate SQL body for filtering and preview resolution."""
    clause_str, args = _build_invitation_candidate_filter_components(filters)
    candidate_key_clause = ""
    if candidate_keys is not None:
        candidate_key_clause = "AND TRIM(COALESCE(i.friend_phone, '')) = ANY(%s)"
        args = list(args)
        args.append(candidate_keys)
        args = tuple(args)
    active_stage_clause = "('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')"

    sql = f"""
        WITH filtered_rows AS (
            SELECT
                i.id AS invitation_id,
                i.member_id AS inviter_member_id,
                i.member_name AS inviter_name,
                NULLIF(TRIM(COALESCE(i.friend_name, '')), '') AS name,
                TRIM(COALESCE(i.friend_phone, '')) AS phone,
                NULLIF(TRIM(COALESCE(i.friend_email, '')), '') AS email,
                i.used_date,
                NULLIF(TRIM(COALESCE(i.used_by, '')), '') AS used_by,
                ROW_NUMBER() OVER (
                    PARTITION BY TRIM(COALESCE(i.friend_phone, ''))
                    ORDER BY i.used_date DESC, i.id DESC
                ) AS phone_rank
            FROM invitations i
            WHERE TRIM(COALESCE(i.friend_phone, '')) <> ''
              AND TRIM(COALESCE(i.friend_phone, '')) ~ '^01[0125][0-9]{{8}}$'
              {candidate_key_clause}
              {clause_str}
        ),
        deduped_candidates AS (
            SELECT
                invitation_id,
                inviter_member_id,
                inviter_name,
                name,
                phone,
                email,
                used_date,
                used_by
            FROM filtered_rows
            WHERE phone_rank = 1
        ),
        eligible_candidates AS (
            SELECT d.*
            FROM deduped_candidates d
            WHERE NOT EXISTS (
                SELECT 1
                FROM members m
                WHERE TRIM(COALESCE(m.phone, '')) = d.phone
            )
              AND NOT EXISTS (
                SELECT 1
                FROM crm_leads l
                WHERE TRIM(COALESCE(l.phone, '')) = d.phone
                  AND l.member_id IS NULL
                AND l.stage IN {active_stage_clause}
                  AND l.is_archived = FALSE
            )
        )
        SELECT
            invitation_id,
            TRIM(COALESCE(phone, '')) AS candidate_key,
            name,
            phone,
            email,
            used_date,
            used_by,
            inviter_member_id,
            inviter_name
        FROM eligible_candidates
        ORDER BY used_date DESC, invitation_id DESC
    """
    return sql, args

def get_invitation_candidate_rows(filters, candidate_keys=None):
    """Returns all eligible invitation candidates matching the supplied filters/keys."""
    sql_body, args = _build_invitation_candidate_sql(filters, candidate_keys)
    query = f"""
        SELECT *
        FROM (
            {sql_body}
        ) AS eligible_candidate_rows
    """
    return [_json_safe_row(row) for row in (query_db(query, args) or [])]

def get_invitation_candidate_listing(filters, page, per_page):
    """Returns a paginated, deduplicated list of invitation-based CRM intake candidates."""
    sql_body, args = _build_invitation_candidate_sql(filters)
    offset = (page - 1) * per_page

    count_query = f"""
        SELECT COUNT(*) AS count
        FROM (
            {sql_body}
        ) AS eligible_count_rows
    """
    count_row = query_db(count_query, args, one=True)
    total_count = count_row['count'] if count_row else 0

    list_query = f"""
        SELECT *
        FROM (
            {sql_body}
            LIMIT %s OFFSET %s
        ) AS eligible_candidate_rows
    """
    rows = [_json_safe_row(row) for row in (query_db(list_query, args + (per_page, offset)) or [])]
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

def get_member_history_member_ids(member_ids):
    """Returns the subset of member IDs that have any CRM lead history."""
    if not member_ids:
        return []
    query = """
        SELECT DISTINCT member_id
        FROM crm_leads
        WHERE member_id = ANY(%s)
          AND member_id IS NOT NULL
    """
    return query_db(query, (member_ids,)) or []

def get_member_campaign_lead_member_ids(member_ids, campaign_id):
    """Returns member IDs that already have at least one lead in the supplied campaign."""
    if not member_ids or campaign_id is None:
        return []
    query = """
        SELECT DISTINCT member_id
        FROM crm_leads
        WHERE member_id = ANY(%s)
          AND member_id IS NOT NULL
          AND campaign_id = %s
    """
    return query_db(query, (member_ids, campaign_id)) or []

def get_member_latest_renewal_times(member_ids):
    """Returns the latest renewal_time for each member ID that has a renewal history."""
    if not member_ids:
        return []
    query = """
        SELECT member_id, MAX(renewal_time) AS latest_renewal_time
        FROM renewal_logs
        WHERE member_id = ANY(%s)
        GROUP BY member_id
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

def create_existing_member_lead_in_transaction(cur, member_row, source, created_by_user_id, assigned_user_id=None, campaign_id=None):
    """Inserts a CRM lead linked to an existing member inside an open transaction."""
    query = """
        INSERT INTO crm_leads (
            member_id, name, phone, email, source, stage,
            campaign_id,
            assigned_user_id, assigned_by_user_id, assigned_at,
            created_by_user_id
        ) VALUES (%s, %s, %s, %s, %s, 'NEW', %s, %s, %s,
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
            campaign_id,
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

def _normalize_invitation_phone(phone):
    if phone is None:
        return None
    return str(phone).strip()

def create_invitation_lead_in_transaction(cur, candidate_row, source, created_by_user_id, assigned_user_id=None):
    """Creates a CRM lead from a frozen invitation candidate inside an open transaction."""
    candidate_key = _normalize_invitation_phone(candidate_row.get('candidate_key'))
    phone = _normalize_invitation_phone(candidate_row.get('phone')) or candidate_key
    invitation_id = candidate_row.get('invitation_id')
    if not candidate_key or not phone or not _INVITATION_PHONE_PATTERN.fullmatch(phone):
        return {"status": "skipped", "reason": "invalid_phone"}
    name = candidate_row.get('name')
    if name is None or not str(name).strip():
        return {
            "status": "skipped",
            "reason": "invalid_candidate_data",
            "details": {"field": "name", "candidate_key": candidate_key}
        }

    lock_key = f"crm_invitation_bulk:{phone}"
    cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s)::bigint)", (lock_key,))

    cur.execute("SELECT id FROM invitations WHERE id = %s LIMIT 1", (invitation_id,))
    if not cur.fetchone():
        return {"status": "skipped", "reason": "invitation_missing", "details": {"invitation_id": invitation_id}}

    cur.execute(
        "SELECT id FROM members WHERE TRIM(COALESCE(phone, '')) = %s LIMIT 1",
        (phone,)
    )
    if cur.fetchone():
        return {"status": "skipped", "reason": "member_now_exists", "details": {"phone": phone}}

    cur.execute(
        """
        SELECT id
        FROM crm_leads
        WHERE TRIM(COALESCE(phone, '')) = %s
          AND member_id IS NULL
          AND stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
          AND is_archived = FALSE
        LIMIT 1
        """,
        (phone,)
    )
    existing_lead = cur.fetchone()
    if existing_lead:
        return {
            "status": "skipped",
            "reason": "crm_lead_now_exists",
            "details": {"existing_lead_id": existing_lead['id'], "phone": phone}
        }

    if assigned_user_id is not None:
        cur.execute(
            """
            SELECT id
            FROM users
            WHERE id = %s
              AND (is_approved = TRUE OR username = 'rino')
            LIMIT 1
            """,
            (assigned_user_id,)
        )
        if not cur.fetchone():
            return {
                "status": "skipped",
                "reason": "invalid_employee",
                "details": {"user_id": assigned_user_id}
            }

    query = """
        INSERT INTO crm_leads (
            member_id, name, phone, email, source, stage,
            assigned_user_id, assigned_by_user_id, assigned_at,
            created_by_user_id
        ) VALUES (NULL, %s, %s, %s, %s, 'NEW', %s, %s,
                  CASE WHEN %s IS NULL THEN NULL ELSE CURRENT_TIMESTAMP END,
                  %s)
        RETURNING id
    """
    cur.execute(
        query,
        (
            str(name).strip(),
            phone,
            candidate_row.get('email'),
            source,
            assigned_user_id,
            created_by_user_id if assigned_user_id is not None else None,
            assigned_user_id,
            created_by_user_id
        )
    )
    created = cur.fetchone()
    return {
        "status": "created",
        "lead_id": created['id'] if created else None,
        "invitation_id": invitation_id,
        "candidate_key": candidate_key,
        "phone": phone
    }

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
        SELECT
            l.*,
            u.username AS assigned_username,
            c.name AS campaign_name,
            NULLIF(TRIM(m.end_date), '') AS member_end_date,
            latest_activity.latest_activity_note,
            latest_activity.latest_activity_at,
            latest_activity.latest_activity_type
        FROM crm_leads l
        LEFT JOIN users u ON u.id = l.assigned_user_id
        LEFT JOIN crm_campaigns c ON c.id = l.campaign_id
        LEFT JOIN members m ON m.id = l.member_id
        LEFT JOIN LATERAL (
            SELECT
                a.note AS latest_activity_note,
                a.created_at AS latest_activity_at,
                a.activity_type AS latest_activity_type
            FROM crm_activities a
            WHERE a.lead_id = l.id
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT 1
        ) latest_activity ON TRUE
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

def create_activity_in_transaction(cur, lead_id, user_id, activity_type, note=None, result=None, old_stage=None, new_stage=None, old_assigned_user_id=None, new_assigned_user_id=None, follow_up_at=None, user_username_snapshot=None):
    """Logs an activity record inside an open transaction cursor."""
    if user_username_snapshot is None and user_id:
        u = get_user_by_id(user_id)
        if u:
            user_username_snapshot = u.get('username')

    query = """
        INSERT INTO crm_activities (
            lead_id, user_id, user_username_snapshot, activity_type, note, result,
            old_stage, new_stage, old_assigned_user_id, new_assigned_user_id, follow_up_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.execute(query, (lead_id, user_id, user_username_snapshot, activity_type, note, result,
                        old_stage, new_stage, old_assigned_user_id, new_assigned_user_id, follow_up_at))

def archive_lead_in_transaction(cur, lead_id):
    """Soft-archives a CRM lead inside an open transaction cursor."""
    query = "UPDATE crm_leads SET is_archived = TRUE, updated_at = CURRENT_TIMESTAMP WHERE id = %s"
    cur.execute(query, (lead_id,))

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
    """Retrieves lead records that have pending follow-up schedules including assigned username."""
    where_str = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
    query = f"""
        SELECT
            l.id,
            l.member_id,
            l.name,
            l.phone,
            l.email,
            l.source,
            l.stage,
            l.assigned_user_id,
            u.username AS assigned_username,
            c.name AS campaign_name,
            l.next_follow_up_at,
            l.is_archived
        FROM crm_leads l
        LEFT JOIN users u ON u.id = l.assigned_user_id
        LEFT JOIN crm_campaigns c ON c.id = l.campaign_id
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
