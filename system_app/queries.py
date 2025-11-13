import os
import psycopg2
from flask import g, current_app
from psycopg2.extras import RealDictCursor  # ← مهم جدًا

# قراءة متغير الاتصال من بيئة التشغيل
DATABASE_URL = os.getenv("DATABASE_URL") or os.getenv("PGURL")
if not DATABASE_URL:
    raise Exception("DATABASE_URL not found. Make sure it's set in Railway Variables.")

# إنشاء اتصال بقاعدة البيانات
def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, sslmode='require')
        g.db.autocommit = True
    return g.db

# إغلاق الاتصال بعد انتهاء الطلب
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

# إنشاء الجداول الأساسية في PostgreSQL
def create_table():
    conn = psycopg2.connect(DATABASE_URL, sslmode='require')
    cr = conn.cursor()
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
    # جدول النسخ الاحتياطي للحضور
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
    conn.close()
    print("PostgreSQL tables created successfully!")

# تنفيذ الاستعلامات العامة (يرجع dict الآن)
def query_db(query, args=(), one=False, commit=False):
    cur = get_db().cursor(cursor_factory=RealDictCursor)  # ← dict
    cur.execute(query, args)
    if commit:
        get_db().commit()
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

# التحقق من وجود اسم
def check_name_exists(name):
    result = query_db('SELECT 1 FROM members WHERE name = %s LIMIT 1', (name,), one=True)
    return result is not None

# التحقق من وجود ID
def check_id_exists(member_id):
    result = query_db('SELECT 1 FROM members WHERE id = %s LIMIT 1', (member_id,), one=True)
    return result is not None
