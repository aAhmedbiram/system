import sqlite3
from flask import g

DATABASE = 'gym_system.db'

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

def close_db(e=None):
    db = g.pop('_database', None)
    if db is not None:
        db.close()

def commit_close():
    db = get_db()
    try:
        db.commit()
    finally:
        close_db()

def create_table():
    conn = sqlite3.connect(DATABASE)
    cr = conn.cursor()

    # جدول الأعضاء
    cr.execute('''
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE,
            phone TEXT,
            age INTEGER,
            gender TEXT,
            birthdate TEXT,
            actual_starting_date TEXT,
            starting_date TEXT,
            End_date TEXT,
            membership_packages TEXT,
            membership_fees REAL,
            membership_status TEXT
        )
    ''')

    # جدول الحضور
    cr.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            num INTEGER PRIMARY KEY AUTOINCREMENT,
            id INTEGER,
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
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # جدول النسخ الاحتياطي (المهم!)
    cr.execute('''
        CREATE TABLE IF NOT EXISTS attendance_backup (
            id INTEGER,
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
    print("All tables created successfully!")

def query_db(query, args=(), one=False):
    cur = get_db().execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def check_name_exists(name):
    result = query_db('SELECT 1 FROM members WHERE name = ? LIMIT 1', (name,), one=True)
    return result is not None

def check_id_exists(member_id):
    result = query_db('SELECT 1 FROM members WHERE id = ? LIMIT 1', (member_id,), one=True)
    return result is not None
