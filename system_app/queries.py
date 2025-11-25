# queries.py - Final guaranteed version on Railway
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import IntegrityError
from datetime import date

# === Read DATABASE_URL ===
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PGURL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found. Make sure it's set in Railway Variables.")

# === Create tables (once on startup) ===
def create_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cr = conn.cursor()
    try:
        cr.execute('''
            CREATE TABLE IF NOT EXISTS members (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE,
                phone TEXT,
                age INTEGER,
                gender TEXT,
                birthdate TEXT,
                actual_starting_date TEXT,
                starting_date TEXT,
                end_date TEXT,
                membership_packages TEXT,
                membership_fees REAL,
                membership_status TEXT,
                invitations INTEGER DEFAULT 0,
                comment TEXT
            )
        ''')
        
        # Add invitations column if it doesn't exist (for existing databases)
        try:
            cr.execute('ALTER TABLE members ADD COLUMN IF NOT EXISTS invitations INTEGER DEFAULT 0')
        except:
            pass
        
        # Add comment column if it doesn't exist (for existing databases)
        try:
            cr.execute('ALTER TABLE members ADD COLUMN IF NOT EXISTS comment TEXT')
        except:
            pass

        cr.execute('''
            CREATE TABLE IF NOT EXISTS attendance (
                num SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                name TEXT,
                end_date TEXT,
                membership_status TEXT,
                attendance_time TEXT,
                attendance_date TEXT,
                day TEXT
            )
        ''')

        cr.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        cr.execute('''
            CREATE TABLE IF NOT EXISTS attendance_backup (
                id SERIAL PRIMARY KEY,
                member_id INTEGER,
                name TEXT,
                end_date TEXT,
                membership_status TEXT,
                attendance_time TEXT,
                attendance_date TEXT,
                day TEXT
            )
        ''')

        cr.execute('''
            CREATE TABLE IF NOT EXISTS member_logs (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                member_name TEXT,
                field_name TEXT NOT NULL,
                old_value TEXT,
                new_value TEXT,
                edited_by TEXT,
                edit_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')

        cr.execute('''
            CREATE TABLE IF NOT EXISTS invitations (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                member_name TEXT NOT NULL,
                friend_name TEXT NOT NULL,
                friend_phone TEXT,
                friend_email TEXT,
                used_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                used_by TEXT
            )
        ''')

        conn.commit()
        print("PostgreSQL tables created successfully!")
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        cr.close()
        conn.close()


# === Execute queries - Final solution: new connection every time ===
def query_db(query, args=(), one=False, commit=False):
    conn = None
    cur = None
    try:
        # Every query = new connection → no stale connection ever
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, args)

        if commit:
            conn.commit()

        # Only fetch results if the query returns rows (SELECT or INSERT/UPDATE with RETURNING)
        # Check if query is a SELECT or has RETURNING clause
        query_upper = query.strip().upper()
        if query_upper.startswith('SELECT') or 'RETURNING' in query_upper:
            rv = cur.fetchall()
            return (rv[0] if rv else None) if one else rv
        else:
            # For INSERT/UPDATE/DELETE without RETURNING, return None or empty list
            return None if one else []

    except IntegrityError as e:
        print(f"DB Integrity Error: {e}")
        if commit and conn:
            conn.rollback()
        raise ValueError("Duplicate entry (email or username already exists)")

    except Exception as e:
        print(f"Query Error: {e}")
        if commit and conn:
            conn.rollback()
        raise e

    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# === Rest of functions (as they are, because they're excellent) ===
def add_member(name, email, phone, age, gender, birthdate,
            actual_starting_date, starting_date, end_date,
            membership_packages, membership_fees, membership_status,
            custom_id=None, invitations=0, comment=None):
    try:
        if custom_id is not None:
            result = query_db('''
                INSERT INTO members 
                (id, name, email, phone, age, gender, birthdate, actual_starting_date, 
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                custom_id, name, email, phone, age, gender, birthdate, actual_starting_date,
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment
            ), one=True, commit=True)
            return result['id']
        else:
            result = query_db('''
                INSERT INTO members 
                (name, email, phone, age, gender, birthdate, actual_starting_date, 
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id
            ''', (
                name, email, phone, age, gender, birthdate, actual_starting_date,
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment
            ), one=True, commit=True)
            return result['id']
    except Exception as e:
        print(f"DB Error in add_member: {e}")
        raise e


def get_member(member_id):
    return query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)


def update_member(member_id, **kwargs):
    if not kwargs:
        return
    # Get old values before updating
    old_member = get_member(member_id)
    if not old_member:
        return
    
    # Extract edited_by for logging (it's not a column in members table)
    edited_by = kwargs.pop('edited_by', 'Unknown')
    member_name = old_member.get('name', 'Unknown')
    
    # Update the member (edited_by is now removed from kwargs)
    if not kwargs:  # If only edited_by was passed, nothing to update
        return
    
    fields = [f"{k} = %s" for k in kwargs.keys()]
    values = list(kwargs.values()) + [member_id]
    query = f"UPDATE members SET {', '.join(fields)} WHERE id = %s"
    query_db(query, tuple(values), commit=True)
    
    # Log the changes
    from datetime import datetime
    for field, new_value in kwargs.items():
        old_value = old_member.get(field)
        
        # Convert values to strings for comparison
        old_str = str(old_value) if old_value is not None else ''
        new_str = str(new_value) if new_value is not None else ''
        
        # Only log if value actually changed
        if old_str != new_str:
            add_member_log(member_id, member_name, field, old_str, new_str, edited_by)


def delete_member(member_id):
    query_db('DELETE FROM members WHERE id = %s', (member_id,), commit=True)


def search_members(name=None, phone=None, email=None):
    conditions = []
    args = []
    if name:
        conditions.append("name ILIKE %s")
        args.append(f"%{name}%")
    if phone:
        conditions.append("phone ILIKE %s")
        args.append(f"%{phone}%")
    if email:
        conditions.append("email ILIKE %s")
        args.append(f"%{email}%")
    
    query = "SELECT * FROM members"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY id DESC"
    return query_db(query, tuple(args))


# === Attendance functions ===
def add_attendance(member_id, name, end_date, membership_status):
    from datetime import datetime
    try:
        now = datetime.now()
        attendance_time = now.strftime("%H:%M:%S")
        attendance_date = now.strftime("%Y-%m-%d")
        day = now.strftime("%A")
        
        query_db('''
            INSERT INTO attendance 
            (member_id, name, end_date, membership_status, attendance_time, attendance_date, day)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (member_id, name, end_date, membership_status, attendance_time, attendance_date, day), commit=True)
        
    except Exception as e:
        print("Error in add_attendance:", e)
        raise e




def get_today_attendance():
    today = date.today().isoformat()
    return query_db('SELECT * FROM attendance WHERE attendance_date = %s ORDER BY num DESC', (today,))


# === User functions ===
def add_user(username, email, password_hash):
    try:
        query_db('INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                (username, email, password_hash), commit=True)
    except IntegrityError:
        raise ValueError("Username or email already exists")


def get_user_by_username(username):
    return query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)


# === Verification functions ===
def check_name_exists(name):
    result = query_db('SELECT 1 FROM members WHERE name = %s LIMIT 1', (name,), one=True)
    return result is not None


def check_id_exists(member_id):
    result = query_db('SELECT 1 FROM members WHERE id = %s LIMIT 1', (member_id,), one=True)
    return result is not None          # ← correct like this


# === Logging functions ===
def add_member_log(member_id, member_name, field_name, old_value, new_value, edited_by):
    """Add a log entry for a member edit"""
    try:
        query_db('''
            INSERT INTO member_logs 
            (member_id, member_name, field_name, old_value, new_value, edited_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (member_id, member_name, field_name, old_value, new_value, edited_by), commit=True)
    except Exception as e:
        print(f"Error adding log: {e}")
        # Don't raise - logging failure shouldn't break the update


def get_member_logs(member_id=None):
    """Get logs for a specific member or all logs"""
    if member_id:
        return query_db('''
            SELECT * FROM member_logs 
            WHERE member_id = %s 
            ORDER BY id ASC
        ''', (member_id,))
    else:
        return query_db('''
            SELECT * FROM member_logs 
            ORDER BY id ASC
        ''')


def get_all_logs():
    """Get all logs ordered by ID ascending"""
    return query_db('''
        SELECT * FROM member_logs 
        ORDER BY id ASC
    ''')


# === Invitation functions ===
def use_invitation(member_id, friend_name, friend_phone=None, friend_email=None, used_by=None):
    """Use one invitation from a member and record the friend's information"""
    try:
        # Get member info
        member = get_member(member_id)
        if not member:
            raise ValueError(f"Member with ID {member_id} not found")
        
        # Check if member has available invitations
        current_invitations = member.get('invitations', 0) or 0
        if current_invitations <= 0:
            raise ValueError(f"Member {member['name']} (ID: {member_id}) has no available invitations")
        
        # Record the invitation usage
        query_db('''
            INSERT INTO invitations 
            (member_id, member_name, friend_name, friend_phone, friend_email, used_by)
            VALUES (%s, %s, %s, %s, %s, %s)
        ''', (member_id, member['name'], friend_name, friend_phone, friend_email, used_by), commit=True)
        
        # Deduct one invitation from member
        query_db('''
            UPDATE members 
            SET invitations = invitations - 1 
            WHERE id = %s
        ''', (member_id,), commit=True)
        
        return True
    except Exception as e:
        print(f"Error using invitation: {e}")
        raise e


def get_all_invitations():
    """Get all invitation records ordered by ID ascending"""
    return query_db('''
        SELECT * FROM invitations 
        ORDER BY id ASC
    ''')


def get_member_invitations(member_id):
    """Get all invitations used by a specific member"""
    return query_db('''
        SELECT * FROM invitations 
        WHERE member_id = %s 
        ORDER BY id ASC
    ''', (member_id,))