# queries.py
import os
import psycopg2
from flask import g
from psycopg2.extras import RealDictCursor
from psycopg2 import IntegrityError
from datetime import date

# === قراءة الـ DATABASE_URL ===
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PGURL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found. Make sure it's set in Railway Variables.")

# === إنشاء وإغلاق الاتصال ===
def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, sslmode='require')
        g.db.autocommit = True
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# === إنشاء الجداول ===
def create_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cr = conn.cursor()
    try:
        # جدول الأعضاء
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
                membership_status TEXT
            )
        ''')

        # جدول الحضور
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

        # جدول المستخدمين
        cr.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')

        # جدول النسخ الاحتياطي
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

        conn.commit()
        print("PostgreSQL tables created successfully!")
    except Exception as e:
        print(f"Error creating tables: {e}")
        conn.rollback()
    finally:
        conn.close()

# === تنفيذ الاستعلامات (آمن + يرجع dict) ===
def query_db(query, args=(), one=False, commit=False):
    db = get_db()
    cur = None
    try:
        cur = db.cursor(cursor_factory=RealDictCursor)
        cur.execute(query, args)
        if commit:
            db.commit()
        rv = cur.fetchall()
        return (rv[0] if rv else None) if one else rv
    except IntegrityError as e:
        print(f"DB Integrity Error: {e}")
        if commit:
            db.rollback()
        raise ValueError("Duplicate entry (email or username already exists)")
    except Exception as e:
        print(f"Query Error: {e}")
        if commit:
            db.rollback()
        raise e
    finally:
        if cur:
            cur.close()

# === دوال الأعضاء (Members) ===
def add_member(name, email, phone, age, gender, birthdate,
               actual_starting_date, starting_date, end_date,
               membership_packages, membership_fees, membership_status):
    """إضافة عضو جديد"""
    try:
        result = query_db('''
            INSERT INTO members 
            (name, email, phone, age, gender, birthdate, actual_starting_date, 
             starting_date, end_date, membership_packages, membership_fees, membership_status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
        ''', (
            name, email, phone, age, gender, birthdate, actual_starting_date,
            starting_date, end_date, membership_packages, membership_fees, membership_status
        ), one=True, commit=True)
        return result['id']
    except Exception as e:
        print(f"DB Error in add_member: {e}")
        raise e

def get_member(member_id):
    """جلب عضو بالـ ID"""
    return query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)

def update_member(member_id, **kwargs):
    """تحديث عضو (أي حقل)"""
    if not kwargs:
        return
    fields = [f"{k} = %s" for k in kwargs.keys()]
    values = list(kwargs.values()) + [member_id]
    query = f"UPDATE members SET {', '.join(fields)} WHERE id = %s"
    query_db(query, tuple(values), commit=True)

def delete_member(member_id):
    """حذف عضو"""
    query_db('DELETE FROM members WHERE id = %s', (member_id,), commit=True)

def search_members(name=None, phone=None, email=None):
    """بحث في الأعضاء"""
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

# === دوال الحضور (Attendance) ===
def add_attendance(member_id, name, end_date, membership_status):
    """تسجيل حضور"""
    from datetime import datetime
    now = datetime.now()
    attendance_time = now.strftime("%H:%M")
    attendance_date = now.strftime("%Y-%m-%d")
    day = now.strftime("%A")
    
    query_db('''
        INSERT INTO attendance 
        (member_id, name, end_date, membership_status, attendance_time, attendance_date, day)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
    ''', (member_id, name, end_date, membership_status, attendance_time, attendance_date, day), commit=True)

def get_today_attendance():
    """جلب حضور اليوم"""
    today = date.today().isoformat()
    return query_db('SELECT * FROM attendance WHERE attendance_date = %s ORDER BY attendance_time DESC', (today,))

# === دوال المستخدمين (Users) ===
def add_user(username, email, password_hash):
    """إضافة مستخدم (للـ Signup)"""
    try:
        query_db('''
            INSERT INTO users (username, email, password)
            VALUES (%s, %s, %s)
        ''', (username, email, password_hash), commit=True)
    except IntegrityError:
        raise ValueError("Username or email already exists")

def get_user_by_username(username):
    """جلب مستخدم للـ Login"""
    return query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)

# === دوال التحقق ===
def check_name_exists(name):
    result = query_db('SELECT 1 FROM members WHERE name = %s LIMIT 1', (name,), one=True)
    return result is not None

def check_id_exists(member_id):
    result = query_db('SELECT 1 FROM members WHERE id = %s LIMIT 1', (member_id,), one=True)
    return result is not None
