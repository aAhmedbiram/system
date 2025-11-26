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
    return query_db('''
        SELECT * FROM supplement_sales 
        ORDER BY sale_date DESC 
        LIMIT %s
    ''', (limit,))


def get_supplement_statistics():
    """Get statistics for supplements"""
    stats = {}
    
    # Total products
    total_products = query_db('SELECT COUNT(*) as count FROM supplements', one=True)
    stats['total_products'] = total_products['count'] if total_products else 0
    
    # Low stock items (stock < 10)
    low_stock = query_db('SELECT COUNT(*) as count FROM supplements WHERE stock_quantity < 10', one=True)
    stats['low_stock'] = low_stock['count'] if low_stock else 0
    
    # Total sales today
    from datetime import datetime
    today = datetime.now().strftime('%Y-%m-%d')
    today_sales = query_db('''
        SELECT COALESCE(SUM(total_price), 0) as total 
        FROM supplement_sales 
        WHERE DATE(sale_date) = %s
    ''', (today,), one=True)
    stats['today_sales'] = float(today_sales['total']) if today_sales else 0
    
    # Total sales this month
    month_start = datetime.now().replace(day=1).strftime('%Y-%m-%d')
    month_sales = query_db('''
        SELECT COALESCE(SUM(total_price), 0) as total 
        FROM supplement_sales 
        WHERE DATE(sale_date) >= %s
    ''', (month_start,), one=True)
    stats['month_sales'] = float(month_sales['total']) if month_sales else 0
    
    # Top selling products
    top_products = query_db('''
        SELECT supplement_name, SUM(quantity) as total_quantity, SUM(total_price) as total_revenue
        FROM supplement_sales
        GROUP BY supplement_name
        ORDER BY total_quantity DESC
        LIMIT 5
    ''')
    stats['top_products'] = top_products or []
    
    # Total inventory value
    inventory_value = query_db('''
        SELECT COALESCE(SUM(stock_quantity * cost), 0) as total 
        FROM supplements
    ''', one=True)
    stats['inventory_value'] = float(inventory_value['total']) if inventory_value else 0
    
    return stats