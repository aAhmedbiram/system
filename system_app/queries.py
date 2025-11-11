import sqlite3
from flask import g
import psycopg2

dbname="rival"
user="rival"
password="01147216302"
host="192.168.56.1"
port="5432"












conn = sqlite3.connect('gym_system.db')


cr = conn.cursor()

DATABASE = 'gym_system.db'


def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
    return db

def commit_close():
    db = getattr(g, '_database', None)
    if db is not None:
        db.commit()
        db.close()
        
def create_table():
    conn = sqlite3.connect('gym_system.db')
    cr = conn.cursor()
    cr.execute('CREATE TABLE IF NOT EXISTS attendance (id INTEGER PRIMARY KEY, date TEXT, member_id INTEGER, member_name TEXT, status TEXT)')
    cr.execute("""CREATE TABLE IF NOT EXISTS members(
            id INTEGER PRIMARY KEY,
            name TEXT, email TEXT,
            phone TEXT,age integer ,
            gender text,
            actual_starting_date integer,
            starting_date integer,
            End_date integer,
            membership_packages text,
            membership_fees integerو
            membership_status text
            )""")
    conn.commit()
    conn.close()

# def query_db(query, args=(), one=False):
#     conn = sqlite3.connect('gym_system.db')
#     conn.row_factory = sqlite3.Row
#     cur = conn.cursor()
#     cur.execute(query, args)
#     rv = cur.fetchall()
#     conn.commit()
#     conn.close()
#     return (rv[0] if rv else None) if one else rv




def query_db(query, args=(), one=False, order_by=None):
    conn = sqlite3.connect('gym_system.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(query, args)
    rv = cur.fetchall()
    conn.commit()
    conn.close()

    if order_by:
        # Use the specified ORDER BY clause
        rv = sorted(rv, key=lambda x: x[order_by], reverse=True)  # Use reverse=True for descending order

    return (rv[0] if rv else None) if one else rv

# In your route, fetch attendance data without specific ordering
# all_attendance_data = query_db("SELECT * FROM attendance", order_by=None)


#cheack name exists
def check_name_exists(name):
    with sqlite3.connect("gym_system.db") as conn:
        cr = conn.cursor()
        cr.execute("SELECT COUNT(*) FROM members WHERE Name = ?", (name,))
        count = cr.fetchone()[0]
        return count > 0



def check_id_exists(id_to_check):
    cr.execute("SELECT COUNT(*) FROM members WHERE id = ?", (id_to_check,))
    count=cr.fetchone()[0]

    return count > 0
