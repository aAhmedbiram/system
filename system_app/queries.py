# queries.py - Final guaranteed version on Railway
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import IntegrityError
from psycopg2 import pool
from datetime import date
import threading

# === Read DATABASE_URL ===
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PGURL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found. Make sure it's set in Railway Variables.")

# === Connection Pool for Performance ===
# Create a connection pool to reuse connections instead of creating new ones
_connection_pool = None
_pool_lock = threading.Lock()

def get_connection_pool():
    """Get or create database connection pool"""
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                try:
                    _connection_pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=1,
                        maxconn=20,  # Maximum 20 connections in pool
                        dsn=DATABASE_URL,
                        sslmode='require'
                    )
                    print("Database connection pool created successfully")
                except Exception as e:
                    print(f"Error creating connection pool: {e}")
                    _connection_pool = None
    return _connection_pool

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
        
        # Add freeze_used column if it doesn't exist (for existing databases)
        try:
            cr.execute('ALTER TABLE members ADD COLUMN IF NOT EXISTS freeze_used BOOLEAN DEFAULT FALSE')
        except:
            pass
        
        # Add email verification columns to users table if they don't exist
        try:
            cr.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS email_verified BOOLEAN DEFAULT FALSE')
        except:
            pass
        try:
            cr.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS verification_token TEXT')
        except:
            pass
        try:
            cr.execute('ALTER TABLE users ADD COLUMN IF NOT EXISTS token_expires TIMESTAMP')
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
                password TEXT NOT NULL,
                email_verified BOOLEAN DEFAULT FALSE,
                verification_token TEXT,
                token_expires TIMESTAMP
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
        
        # Create action_logs table for undo functionality
        cr.execute('''
            CREATE TABLE IF NOT EXISTS action_logs (
                id SERIAL PRIMARY KEY,
                action_type TEXT NOT NULL,
                member_id INTEGER,
                member_name TEXT,
                action_data JSONB,
                performed_by TEXT,
                action_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                undone BOOLEAN DEFAULT FALSE,
                undo_time TIMESTAMP
            )
        ''')
        
        # Add undone column if it doesn't exist (for existing databases)
        try:
            cr.execute('ALTER TABLE action_logs ADD COLUMN IF NOT EXISTS undone BOOLEAN DEFAULT FALSE')
        except:
            pass
        try:
            cr.execute('ALTER TABLE action_logs ADD COLUMN IF NOT EXISTS undo_time TIMESTAMP')
        except:
            pass

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
        
        # Create supplements/products table
        cr.execute('''
            CREATE TABLE IF NOT EXISTS supplements (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                category TEXT,
                subcategory TEXT,
                price REAL DEFAULT 0,
                cost REAL DEFAULT 0,
                stock_quantity INTEGER DEFAULT 0,
                unit TEXT DEFAULT 'piece',
                description TEXT,
                supplier TEXT,
                barcode TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create supplement sales table
        cr.execute('''
            CREATE TABLE IF NOT EXISTS supplement_sales (
                id SERIAL PRIMARY KEY,
                supplement_id INTEGER REFERENCES supplements(id) ON DELETE CASCADE,
                supplement_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                sale_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                sold_by TEXT,
                customer_name TEXT,
                payment_method TEXT DEFAULT 'cash'
            )
        ''')
        
        # Create staff table
        cr.execute('''
            CREATE TABLE IF NOT EXISTS staff (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                role TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                hire_date DATE,
                status TEXT DEFAULT 'active',
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Create staff purchases table
        cr.execute('''
            CREATE TABLE IF NOT EXISTS staff_purchases (
                id SERIAL PRIMARY KEY,
                staff_id INTEGER REFERENCES staff(id) ON DELETE CASCADE,
                staff_name TEXT NOT NULL,
                supplement_id INTEGER REFERENCES supplements(id) ON DELETE SET NULL,
                supplement_name TEXT NOT NULL,
                quantity INTEGER NOT NULL,
                unit_price REAL NOT NULL,
                total_price REAL NOT NULL,
                purchase_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                notes TEXT,
                recorded_by TEXT
            )
        ''')
        
        # Create renewal_logs table to track membership renewals
        cr.execute('''
            CREATE TABLE IF NOT EXISTS renewal_logs (
                id SERIAL PRIMARY KEY,
                member_id INTEGER REFERENCES members(id) ON DELETE CASCADE,
                package_name TEXT NOT NULL,
                renewal_date DATE NOT NULL,
                renewal_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                fees REAL NOT NULL,
                edited_by TEXT
            )
        ''')

        # Create indexes for better query performance
        try:
            # Indexes for members table (frequently queried columns)
            cr.execute('CREATE INDEX IF NOT EXISTS idx_members_name ON members(name)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_members_phone ON members(phone)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_members_email ON members(email)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_members_id ON members(id)')
            
            # Indexes for attendance table
            cr.execute('CREATE INDEX IF NOT EXISTS idx_attendance_member_id ON attendance(member_id)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_attendance_date ON attendance(attendance_date)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_attendance_num ON attendance(num)')
            
            # Indexes for member_logs table
            cr.execute('CREATE INDEX IF NOT EXISTS idx_member_logs_member_id ON member_logs(member_id)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_member_logs_edit_time ON member_logs(edit_time)')
            
            # Indexes for invitations table
            cr.execute('CREATE INDEX IF NOT EXISTS idx_invitations_member_id ON invitations(member_id)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_invitations_used_date ON invitations(used_date)')
            
            # Indexes for action_logs table
            cr.execute('CREATE INDEX IF NOT EXISTS idx_action_logs_member_id ON action_logs(member_id)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_action_logs_action_time ON action_logs(action_time)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_action_logs_undone ON action_logs(undone)')
            
            # Indexes for supplements tables
            cr.execute('CREATE INDEX IF NOT EXISTS idx_supplements_name ON supplements(name)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_supplements_category ON supplements(category)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_supplement_sales_date ON supplement_sales(sale_date)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_supplement_sales_supplement_id ON supplement_sales(supplement_id)')
            
            # Indexes for staff tables
            cr.execute('CREATE INDEX IF NOT EXISTS idx_staff_role ON staff(role)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_staff_status ON staff(status)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_staff_purchases_staff_id ON staff_purchases(staff_id)')
            cr.execute('CREATE INDEX IF NOT EXISTS idx_staff_purchases_date ON staff_purchases(purchase_date)')
            
            conn.commit()
            print("PostgreSQL tables and indexes created successfully!")
        except Exception as e:
            print(f"Error creating indexes: {e}")
            # Don't fail if indexes already exist
            conn.rollback()

        conn.commit()
        print("PostgreSQL tables created successfully!")
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        cr.close()
        conn.close()


# === Execute queries - Using connection pool for better performance ===
def query_db(query, args=(), one=False, commit=False):
    """Execute query using connection pool for better performance"""
    pool = get_connection_pool()
    conn = None
    cur = None
    
    # Fallback to direct connection if pool fails
    if pool is None:
        try:
            conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        except Exception as e:
            print(f"Error creating direct connection: {e}")
            raise e
    else:
        try:
            conn = pool.getconn()
        except Exception as e:
            print(f"Error getting connection from pool: {e}")
            # Fallback to direct connection
            try:
                conn = psycopg2.connect(DATABASE_URL, sslmode='require')
            except Exception as fallback_error:
                print(f"Fallback connection also failed: {fallback_error}")
                raise fallback_error
    
    try:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, args)

        if commit:
            conn.commit()

        # Only fetch results if the query returns rows (SELECT or INSERT/UPDATE with RETURNING)
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
            if pool:
                # Return connection to pool
                try:
                    pool.putconn(conn)
                except Exception as e:
                    print(f"Error returning connection to pool: {e}")
                    conn.close()  # Close if can't return to pool
            else:
                # Direct connection - close it
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


def bulk_add_members(members_list):
    """
    Bulk insert members for faster import.
    members_list: List of tuples, each tuple contains member data in order:
    (custom_id, name, email, phone, age, gender, birthdate, actual_starting_date,
     starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment)
    Returns: number of successfully inserted members
    """
    if not members_list:
        return 0
    
    conn = None
    cur = None
    inserted = 0
    
    try:
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        # Check if first member has custom_id
        has_custom_id = members_list[0][0] is not None if len(members_list) > 0 else False
        
        if has_custom_id:
            # Bulk insert with custom_id
            insert_query = '''
                INSERT INTO members 
                (id, name, email, phone, age, gender, birthdate, actual_starting_date, 
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            '''
        else:
            # Bulk insert without custom_id
            insert_query = '''
                INSERT INTO members 
                (name, email, phone, age, gender, birthdate, actual_starting_date, 
                starting_date, end_date, membership_packages, membership_fees, membership_status, invitations, comment)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            '''
        
        # Use execute_batch for efficient bulk insert
        from psycopg2.extras import execute_batch
        execute_batch(cur, insert_query, members_list, page_size=len(members_list))
        
        conn.commit()
        inserted = len(members_list)
        
    except Exception as e:
        if conn:
            conn.rollback()
        print(f"Bulk insert error: {e}")
        # Fall back to individual inserts if bulk fails
        print("Falling back to individual inserts...")
        for member_data in members_list:
            try:
                if has_custom_id:
                    add_member(
                        name=member_data[1],
                        email=member_data[2],
                        phone=member_data[3],
                        age=member_data[4],
                        gender=member_data[5],
                        birthdate=member_data[6],
                        actual_starting_date=member_data[7],
                        starting_date=member_data[8],
                        end_date=member_data[9],
                        membership_packages=member_data[10],
                        membership_fees=member_data[11],
                        membership_status=member_data[12],
                        invitations=member_data[13],
                        comment=member_data[14],
                        custom_id=member_data[0]
                    )
                else:
                    add_member(
                        name=member_data[0],
                        email=member_data[1],
                        phone=member_data[2],
                        age=member_data[3],
                        gender=member_data[4],
                        birthdate=member_data[5],
                        actual_starting_date=member_data[6],
                        starting_date=member_data[7],
                        end_date=member_data[8],
                        membership_packages=member_data[9],
                        membership_fees=member_data[10],
                        membership_status=member_data[11],
                        invitations=member_data[12],
                        comment=member_data[13]
                    )
                inserted += 1
            except Exception as individual_error:
                print(f"Error inserting individual member: {individual_error}")
                continue
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    
    return inserted


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


def delete_all_data():
    """Delete all data from all tables (except users table)"""
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cur = conn.cursor()
    try:
        # Use CASCADE to truncate members table and all child tables that reference it
        # This will automatically truncate: attendance, member_logs, invitations
        cur.execute('TRUNCATE TABLE members RESTART IDENTITY CASCADE')
        
        # Truncate attendance_backup separately (it has no foreign keys to members)
        cur.execute('TRUNCATE TABLE attendance_backup RESTART IDENTITY')
        
        conn.commit()
        print("All data deleted successfully!")
        print("Deleted: All Members, All Attendance Records, All Edit Logs, All Invitation Records, All Attendance Backup Records")
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error deleting all data: {e}")
        import traceback
        traceback.print_exc()
        raise e
    finally:
        cur.close()
        conn.close()


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


# === Action Logging for Undo ===
try:
    import json
except ImportError:
    import simplejson as json

def log_action(action_type, member_id=None, member_name=None, action_data=None, performed_by=None):
    """Log an action for undo functionality"""
    try:
        action_data_json = json.dumps(action_data) if action_data else None
        query_db('''
            INSERT INTO action_logs 
            (action_type, member_id, member_name, action_data, performed_by)
            VALUES (%s, %s, %s, %s, %s)
        ''', (action_type, member_id, member_name, action_data_json, performed_by), commit=True)
    except Exception as e:
        print(f"Error logging action: {e}")
        import traceback
        traceback.print_exc()


def get_undoable_actions(limit=100):
    """Get recent actions that can be undone"""
    try:
        return query_db('''
            SELECT * FROM action_logs 
            WHERE undone = FALSE
            ORDER BY action_time DESC
            LIMIT %s
        ''', (limit,))
    except Exception as e:
        print(f"Error getting undoable actions: {e}")
        return []


def mark_action_undone(action_id):
    """Mark an action as undone"""
    try:
        query_db('''
            UPDATE action_logs 
            SET undone = TRUE, undo_time = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (action_id,), commit=True)
    except Exception as e:
        print(f"Error marking action as undone: {e}")
        raise


def get_action_by_id(action_id):
    """Get a specific action by ID"""
    try:
        return query_db('SELECT * FROM action_logs WHERE id = %s', (action_id,), one=True)
    except Exception as e:
        print(f"Error getting action: {e}")
        return None


# === Invitation functions ===
def use_invitation(member_id, friend_name, friend_phone=None, friend_email=None, used_by=None):
    """Use one invitation from a member and record the friend's information"""
    try:
        # Get member info
        member = get_member(member_id)
        if not member:
            raise ValueError(f"Member with ID {member_id} not found")
        
        # Check if member's end date has expired
        end_date_str = member.get('end_date')
        if end_date_str:
            from datetime import datetime
            
            try:
                # Parse the end date - handle various formats
                if isinstance(end_date_str, str):
                    end_date_str = end_date_str.strip()
                    end_date = None
                    
                    # Try common date formats
                    date_formats = [
                        '%Y-%m-%d',      # 2024-12-31
                        '%m/%d/%Y',       # 12/31/2024
                        '%d/%m/%Y',       # 31/12/2024
                        '%m-%d-%Y',       # 12-31-2024
                        '%d-%m-%Y',       # 31-12-2024
                        '%Y/%m/%d',       # 2024/12/31
                    ]
                    
                    for fmt in date_formats:
                        try:
                            end_date = datetime.strptime(end_date_str, fmt).date()
                            break
                        except ValueError:
                            continue
                    
                    # If parsing succeeded, check if expired
                    if end_date:
                        today = datetime.now().date()
                        if end_date < today:
                            raise ValueError(f"Member {member['name']} (ID: {member_id}) cannot use invitations because their membership has expired. End date: {end_date_str}")
                    else:
                        # If we couldn't parse the date, log warning but allow (graceful degradation)
                        print(f"Warning: Could not parse end_date '{end_date_str}' for member {member_id}. Allowing invitation usage.")
            except ValueError as ve:
                # Re-raise ValueError (our custom error about expired membership)
                raise ve
            except Exception as e:
                # For other exceptions, log but don't block
                print(f"Warning: Error checking end date for member {member_id}: {e}")
        
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


def log_renewal(member_id, package_name, renewal_date, fees, edited_by=None):
    """Log a membership renewal when start_date is edited"""
    try:
        from datetime import datetime
        # Parse renewal_date to ensure it's a date
        if isinstance(renewal_date, str):
            # Try to parse various date formats
            date_formats = [
                '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y',
                '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d'
            ]
            renewal_date_parsed = None
            for fmt in date_formats:
                try:
                    renewal_date_parsed = datetime.strptime(renewal_date.strip()[:10], fmt).date()
                    break
                except (ValueError, IndexError):
                    continue
            if renewal_date_parsed:
                renewal_date = renewal_date_parsed
            else:
                print(f"Warning: Could not parse renewal_date: {renewal_date}")
                return False
        
        query_db('''
            INSERT INTO renewal_logs (member_id, package_name, renewal_date, fees, edited_by)
            VALUES (%s, %s, %s, %s, %s)
        ''', (member_id, package_name, renewal_date, fees, edited_by), commit=True)
        return True
    except Exception as e:
        print(f"Error logging renewal: {e}")
        return False


def get_renewal_logs():
    """Get all renewal logs ordered by renewal_date"""
    return query_db(
        'SELECT * FROM renewal_logs ORDER BY renewal_date DESC, renewal_time DESC',
        ()
    )


def get_daily_totals():
    """Get daily income totals from renewals"""
    try:
        return query_db('''
            SELECT 
                renewal_date::date as date,
                SUM(fees) as sum
            FROM renewal_logs
            GROUP BY renewal_date::date
            ORDER BY renewal_date::date DESC
        ''', ())
    except Exception as e:
        print(f"Error getting daily totals: {e}")
        return []


def get_monthly_total(year=None, month=None):
    """Get total income for a specific month"""
    try:
        from datetime import datetime
        if not year or not month:
            now = datetime.now()
            year = now.year
            month = now.month
        
        result = query_db('''
            SELECT SUM(fees) as total
            FROM renewal_logs
            WHERE EXTRACT(YEAR FROM renewal_date) = %s
            AND EXTRACT(MONTH FROM renewal_date) = %s
        ''', (year, month), one=True)
        
        return result.get('total', 0) if result else 0
    except Exception as e:
        print(f"Error getting monthly total: {e}")
        return 0


# === Supplement/Product Management Functions ===
def add_supplement(name, category=None, subcategory=None, price=0, cost=0, stock_quantity=0, unit='piece', description=None, supplier=None, barcode=None):
    """Add a new supplement/product"""
    try:
        result = query_db('''
            INSERT INTO supplements 
            (name, category, subcategory, price, cost, stock_quantity, unit, description, supplier, barcode)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (name, category, subcategory, price, cost, stock_quantity, unit, description, supplier, barcode), one=True, commit=True)
        return result['id'] if result else None
    except Exception as e:
        print(f"Error adding supplement: {e}")
        raise e


def get_supplement(supplement_id):
    """Get a supplement by ID"""
    return query_db('SELECT * FROM supplements WHERE id = %s', (supplement_id,), one=True)


def get_all_supplements():
    """Get all supplements"""
    return query_db('SELECT * FROM supplements ORDER BY name ASC')


def update_supplement(supplement_id, **kwargs):
    """Update supplement fields"""
    if not kwargs:
        return
    from datetime import datetime
    kwargs['updated_at'] = datetime.now()
    fields = [f"{k} = %s" for k in kwargs.keys()]
    values = list(kwargs.values()) + [supplement_id]
    query = f"UPDATE supplements SET {', '.join(fields)} WHERE id = %s"
    query_db(query, tuple(values), commit=True)


def delete_supplement(supplement_id):
    """Delete a supplement"""
    query_db('DELETE FROM supplements WHERE id = %s', (supplement_id,), commit=True)


def add_supplement_sale(supplement_id, supplement_name, quantity, unit_price, total_price, sold_by=None, customer_name=None, payment_method='cash'):
    """Record a supplement sale"""
    try:
        # Record the sale
        query_db('''
            INSERT INTO supplement_sales 
            (supplement_id, supplement_name, quantity, unit_price, total_price, sold_by, customer_name, payment_method)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ''', (supplement_id, supplement_name, quantity, unit_price, total_price, sold_by, customer_name, payment_method), commit=True)
        
        # Update stock quantity
        query_db('''
            UPDATE supplements 
            SET stock_quantity = stock_quantity - %s, updated_at = CURRENT_TIMESTAMP
            WHERE id = %s
        ''', (quantity, supplement_id), commit=True)
    except Exception as e:
        print(f"Error adding supplement sale: {e}")
        raise e


def get_supplement_sales(limit=100):
    """Get recent supplement sales"""
    try:
        return query_db('''
            SELECT * FROM supplement_sales 
            ORDER BY sale_date DESC 
            LIMIT %s
        ''', (limit,))
    except Exception as e:
        print(f"Error getting supplement sales: {e}")
        return []


def get_supplement_statistics():
    """Get statistics for supplements"""
    stats = {}
    
    try:
        # Total products
        total_products = query_db('SELECT COUNT(*) as count FROM supplements', one=True)
        stats['total_products'] = total_products['count'] if total_products else 0
    except Exception as e:
        print(f"Error getting total products: {e}")
        stats['total_products'] = 0
    
    try:
        # Low stock items (stock < 10)
        low_stock = query_db('SELECT COUNT(*) as count FROM supplements WHERE stock_quantity < 10', one=True)
        stats['low_stock'] = low_stock['count'] if low_stock else 0
    except Exception as e:
        print(f"Error getting low stock: {e}")
        stats['low_stock'] = 0
    
    # Total sales today
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    try:
        today_sales = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM supplement_sales 
            WHERE sale_date::date = %s
        ''', (today,), one=True)
        stats['today_sales'] = float(today_sales['total']) if today_sales else 0
    except:
        stats['today_sales'] = 0
    
    # Cash sales today
    try:
        cash_sales_today = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM supplement_sales 
            WHERE sale_date::date = %s AND payment_method = 'cash'
        ''', (today,), one=True)
        stats['cash_sales_today'] = float(cash_sales_today['total']) if cash_sales_today else 0
    except:
        stats['cash_sales_today'] = 0
    
    # Visa/Card sales today
    try:
        visa_sales_today = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM supplement_sales 
            WHERE sale_date::date = %s AND (payment_method = 'card' OR payment_method = 'visa')
        ''', (today,), one=True)
        stats['visa_sales_today'] = float(visa_sales_today['total']) if visa_sales_today else 0
    except:
        stats['visa_sales_today'] = 0
    
    # Total sales this month
    month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    try:
        month_sales = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM supplement_sales 
            WHERE sale_date::date >= %s
        ''', (month_start,), one=True)
        stats['month_sales'] = float(month_sales['total']) if month_sales else 0
    except:
        stats['month_sales'] = 0
    
    # Total all-time sales
    try:
        total_sales = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM supplement_sales
        ''', one=True)
        stats['total_sales'] = float(total_sales['total']) if total_sales else 0
    except Exception as e:
        print(f"Error getting total sales: {e}")
        stats['total_sales'] = 0
    
    # Total sales count
    try:
        total_sales_count = query_db('''
            SELECT COUNT(*) as count 
            FROM supplement_sales
        ''', one=True)
        stats['total_sales_count'] = total_sales_count['count'] if total_sales_count else 0
    except Exception as e:
        print(f"Error getting total sales count: {e}")
        stats['total_sales_count'] = 0
    
    # Top selling products
    try:
        top_products = query_db('''
            SELECT supplement_name, SUM(quantity) as total_quantity, SUM(total_price) as total_revenue, COUNT(*) as sales_count
            FROM supplement_sales
            GROUP BY supplement_name
            ORDER BY total_quantity DESC
            LIMIT 5
        ''')
        stats['top_products'] = top_products or []
    except Exception as e:
        print(f"Error getting top products: {e}")
        stats['top_products'] = []
    
    # Per-product statistics
    try:
        product_stats = query_db('''
            SELECT 
                s.id,
                s.name,
                s.stock_quantity,
                s.cost,
                COALESCE(SUM(sa.quantity), 0) as total_sold,
                COALESCE(SUM(sa.total_price), 0) as total_revenue,
                COALESCE(COUNT(sa.id), 0) as sales_count,
                (s.stock_quantity * s.cost) as inventory_value
            FROM supplements s
            LEFT JOIN supplement_sales sa ON s.id = sa.supplement_id
            GROUP BY s.id, s.name, s.stock_quantity, s.cost
            ORDER BY s.name ASC
        ''')
        stats['product_stats'] = product_stats or []
    except Exception as e:
        print(f"Error getting product stats: {e}")
        stats['product_stats'] = []
    
    # Total inventory value
    try:
        inventory_value = query_db('''
            SELECT COALESCE(SUM(stock_quantity * cost), 0) as total 
            FROM supplements
        ''', one=True)
        stats['inventory_value'] = float(inventory_value['total']) if inventory_value else 0
    except Exception as e:
        print(f"Error getting inventory value: {e}")
        stats['inventory_value'] = 0
    
    # Per-user sales statistics
    try:
        user_sales = query_db('''
            SELECT 
                sold_by,
                COUNT(*) as sales_count,
                SUM(quantity) as total_quantity,
                SUM(total_price) as total_revenue,
                SUM(CASE WHEN payment_method = 'cash' THEN total_price ELSE 0 END) as cash_revenue,
                SUM(CASE WHEN payment_method = 'card' OR payment_method = 'visa' THEN total_price ELSE 0 END) as card_revenue
            FROM supplement_sales
            WHERE sold_by IS NOT NULL
            GROUP BY sold_by
            ORDER BY total_revenue DESC
        ''')
        stats['user_sales'] = user_sales or []
    except Exception as e:
        print(f"Error getting user sales: {e}")
        stats['user_sales'] = []
    
    # Per-user sales today
    try:
        user_sales_today = query_db('''
            SELECT 
                sold_by,
                COUNT(*) as sales_count,
                SUM(quantity) as total_quantity,
                SUM(total_price) as total_revenue
            FROM supplement_sales
            WHERE sold_by IS NOT NULL AND sale_date::date = %s
            GROUP BY sold_by
            ORDER BY total_revenue DESC
        ''', (today,))
        stats['user_sales_today'] = user_sales_today or []
    except:
        stats['user_sales_today'] = []
    
    return stats


# === Staff Management Functions ===
def add_staff(name, role, phone=None, email=None, hire_date=None, status='active', notes=None):
    """Add a new staff member"""
    try:
        result = query_db('''
            INSERT INTO staff (name, role, phone, email, hire_date, status, notes)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (name, role, phone, email, hire_date, status, notes), one=True, commit=True)
        return result['id'] if result else None
    except Exception as e:
        print(f"Error adding staff: {e}")
        raise e


def get_staff(staff_id):
    """Get a staff member by ID"""
    try:
        return query_db('SELECT * FROM staff WHERE id = %s', (staff_id,), one=True)
    except Exception as e:
        print(f"Error getting staff: {e}")
        return None


def get_all_staff():
    """Get all staff members"""
    try:
        return query_db('SELECT * FROM staff ORDER BY name ASC')
    except Exception as e:
        print(f"Error getting all staff: {e}")
        return []


def update_staff(staff_id, **kwargs):
    """Update staff fields"""
    if not kwargs:
        return
    try:
        from datetime import datetime
        kwargs['updated_at'] = datetime.now()
        fields = [f"{k} = %s" for k in kwargs.keys()]
        values = list(kwargs.values()) + [staff_id]
        query = f"UPDATE staff SET {', '.join(fields)} WHERE id = %s"
        query_db(query, tuple(values), commit=True)
    except Exception as e:
        print(f"Error updating staff: {e}")
        raise e


def delete_staff(staff_id):
    """Delete a staff member"""
    try:
        query_db('DELETE FROM staff WHERE id = %s', (staff_id,), commit=True)
    except Exception as e:
        print(f"Error deleting staff: {e}")
        raise e


def add_staff_purchase(staff_id, staff_name, supplement_id, supplement_name, quantity, unit_price, total_price, notes=None, recorded_by=None):
    """Record a staff purchase"""
    try:
        query_db('''
            INSERT INTO staff_purchases 
            (staff_id, staff_name, supplement_id, supplement_name, quantity, unit_price, total_price, notes, recorded_by)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        ''', (staff_id, staff_name, supplement_id, supplement_name, quantity, unit_price, total_price, notes, recorded_by), commit=True)
        
        # Update stock quantity
        if supplement_id:
            query_db('''
                UPDATE supplements 
                SET stock_quantity = stock_quantity - %s, updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
            ''', (quantity, supplement_id), commit=True)
    except Exception as e:
        print(f"Error adding staff purchase: {e}")
        raise e


def get_staff_purchases(staff_id=None, limit=100):
    """Get staff purchases"""
    try:
        if staff_id:
            return query_db('''
                SELECT * FROM staff_purchases 
                WHERE staff_id = %s
                ORDER BY purchase_date DESC 
                LIMIT %s
            ''', (staff_id, limit))
        else:
            return query_db('''
                SELECT * FROM staff_purchases 
                ORDER BY purchase_date DESC 
                LIMIT %s
            ''', (limit,))
    except Exception as e:
        print(f"Error getting staff purchases: {e}")
        return []


def get_staff_statistics():
    """Get statistics for staff"""
    stats = {}
    
    try:
        # Total staff
        total_staff = query_db('SELECT COUNT(*) as count FROM staff WHERE status = %s', ('active',), one=True)
        stats['total_staff'] = total_staff['count'] if total_staff else 0
    except Exception as e:
        print(f"Error getting total staff: {e}")
        stats['total_staff'] = 0
    
    try:
        # Staff by role
        staff_by_role = query_db('''
            SELECT role, COUNT(*) as count 
            FROM staff 
            WHERE status = 'active'
            GROUP BY role
        ''')
        stats['staff_by_role'] = staff_by_role or []
    except Exception as e:
        print(f"Error getting staff by role: {e}")
        stats['staff_by_role'] = []
    
    try:
        # Per-staff purchase statistics
        staff_purchase_stats = query_db('''
            SELECT 
                s.id,
                s.name,
                s.role,
                COALESCE(COUNT(sp.id), 0) as purchase_count,
                COALESCE(SUM(sp.quantity), 0) as total_quantity,
                COALESCE(SUM(sp.total_price), 0) as total_spent
            FROM staff s
            LEFT JOIN staff_purchases sp ON s.id = sp.staff_id
            WHERE s.status = 'active'
            GROUP BY s.id, s.name, s.role
            ORDER BY total_spent DESC
        ''')
        stats['staff_purchase_stats'] = staff_purchase_stats or []
    except Exception as e:
        print(f"Error getting staff purchase stats: {e}")
        stats['staff_purchase_stats'] = []
    
    try:
        # Total staff purchases
        total_staff_purchases = query_db('''
            SELECT 
                COALESCE(SUM(total_price), 0) as total,
                COALESCE(COUNT(*), 0) as count,
                COALESCE(SUM(quantity), 0) as total_quantity
            FROM staff_purchases
        ''', one=True)
        stats['total_staff_purchases'] = float(total_staff_purchases['total']) if total_staff_purchases else 0
        stats['total_staff_purchase_count'] = total_staff_purchases['count'] if total_staff_purchases else 0
        stats['total_staff_purchase_quantity'] = total_staff_purchases['total_quantity'] if total_staff_purchases else 0
    except Exception as e:
        print(f"Error getting total staff purchases: {e}")
        stats['total_staff_purchases'] = 0
        stats['total_staff_purchase_count'] = 0
        stats['total_staff_purchase_quantity'] = 0
    
    try:
        # Staff purchases this month
        from datetime import datetime
        month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
        month_staff_purchases = query_db('''
            SELECT COALESCE(SUM(total_price), 0) as total 
            FROM staff_purchases 
            WHERE purchase_date::date >= %s
        ''', (month_start,), one=True)
        stats['month_staff_purchases'] = float(month_staff_purchases['total']) if month_staff_purchases else 0
    except Exception as e:
        print(f"Error getting month staff purchases: {e}")
        stats['month_staff_purchases'] = 0
    
    return stats