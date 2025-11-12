import os
import psycopg2
from flask import g

DATABASE_URL = os.environ['DATABASE_URL']

def get_db():
    if 'db' not in g:
        g.db = psycopg2.connect(DATABASE_URL, sslmode='require')
        g.db.autocommit = True
    return g.db

def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

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
            End_date TEXT,
            membership_packages TEXT,
            membership_fees REAL,
            membership_status TEXT
        )
    ''')

    # جدول الحضور
    cr.execute('''
        CREATE TABLE IF NOT EXISTS attendance (
            num SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
            username TEXT UNIQUE NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL
        )
    ''')

    # جدول النسخ الاحتياطي
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

    conn.close()
    print("PostgreSQL tables created successfully!")

def query_db(query, args=(), one=False):
    cur = get_db().cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    cur.close()
    return (rv[0] if rv else None) if one else rv

def check_name_exists(name):
    result = query_db('SELECT 1 FROM members WHERE name = %s LIMIT 1', (name,), one=True)
    return result is not None

def check_id_exists(member_id):
    result = query_db('SELECT 1 FROM members WHERE id = %s LIMIT 1', (member_id,), one=True)
    return result is not None
