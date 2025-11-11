from flask import Flask, render_template, request, redirect, url_for, flash, session, jsonify
from datetime import datetime
import calendar
import sqlite3
import os

# ✅ Relative imports (لأن كل حاجة جوا system_app)
from .func import get_age_and_dob, add_member, calculate_age, calculate_end_date, membership_fees, compare_dates
from .queries import create_table, query_db, check_name_exists, check_id_exists, get_db, commit_close

from flask import g
from .queries import create_table, close_db  # ← تأكد إن close_db مستوردة هنا

from .queries import create_table, close_db

app = Flask(__name__)
app.secret_key = 'my secret key'

# # إنشاء الجداول عند بدء التطبيق
# with app.app_context():
#     create_table()

# # إغلاق الـ DB بعد كل طلب
# @app.teardown_appcontext
# def teardown_db(exception):
#     close_db()

def init_db():
    """هتعمل الجداول لو مش موجودة"""
    try:
        create_table()
        print("✅ Database initialized successfully!")  # للـ logs
    except Exception as e:
        print(f"❌ DB Error: {e}")  # للـ logs

init_db()  # شغلها فورًا

# # باقي الروتس زي ما هي...
# @app.route('/')
# def home():
#     return "التطبيق شغال 100% يا وحش! 🎉"

@app.route('/login')
def login():
    return render_template('login.html')

@app.route("/home")
def index():
    attendance_data = query_db('SELECT * FROM attendance')
    members_data = query_db('SELECT * FROM members')
    return render_template("index.html", attendance_data=attendance_data, members_data=members_data)

@app.route('/search', methods=['GET', 'POST'])
def search_by_name():
    if request.method == 'POST':
        name_to_check = request.form['name']
        exists = check_name_exists(name_to_check)
        if exists:
            with sqlite3.connect("gym_system.db") as conn:
                cr = conn.cursor()
                cr.execute("SELECT * FROM members WHERE name = ?", (name_to_check,))
                show_data = cr.fetchone()
                return render_template('result.html', name=name_to_check, data=show_data)
        else:
            return render_template('result.html', name=name_to_check, data=None)
    return render_template('search.html')

# باقي الروتس زي ما هي (مش هتتغير)
# ... (كل الكود من add_member_route لحد logout)

@app.route("/add_member", methods=["POST"])
def add_member_route():
    if request.method == "POST":
        member_name = request.form.get("member_name").capitalize()
        member_email = request.form.get("member_email")
        member_phone = request.form.get("member_phone")
        member_age = calculate_age(request.form.get("member_age"))
        member_gender = request.form.get("choice")
        member_birthdate = request.form.get("member_age")
        member_actual_starting_date = request.form.get("member_actual_starting_date")
        member_starting_date = request.form.get("member_starting_date")
        user_input = request.form.get("member_membership_packages")
        try:
            numeric_value, unit = user_input.split(maxsplit=1) if user_input else (None, None)
        except ValueError:
            numeric_value, unit = ("wrong package", "")
        member_End_date = calculate_end_date(member_starting_date, numeric_value)
        member_membership_fees = membership_fees(user_input)
        member_membership_status = compare_dates(member_End_date)
        new_member_id = add_member(
            member_name, member_email, member_phone, member_age, member_gender, member_birthdate,
            member_actual_starting_date, member_starting_date, member_End_date,
            f"{numeric_value} {unit}", member_membership_fees, member_membership_status
        )
        parsed_date = datetime.strptime(member_actual_starting_date, '%Y-%m-%d')
        formatted_date = parsed_date.strftime('%d,%m,%Y')
        return redirect(url_for("add_member_done", new_member_id=new_member_id, formatted_date=formatted_date))
    return redirect(url_for("index"))

@app.route("/add_member_done/<int:new_member_id>")
def add_member_done(new_member_id):
    return render_template("add_member_done.html",new_member_id=new_member_id)

@app.route("/all_members")
def all_members():
    members_data = query_db('SELECT * FROM members')
    return render_template("all_members.html", members_data=members_data)

@app.route("/edit_member/<int:member_id>", methods=["GET", "POST"])
def edit_member(member_id):
    if request.method == "GET":
        member = query_db('SELECT * FROM members WHERE id = ?', (member_id,), one=True)
        return render_template("edit_member.html", member=member)
    elif request.method == "POST":
        edit_member_name = request.form.get("edit_member_name").capitalize()
        edit_member_email = request.form.get("edit_member_email")
        edit_member_phone = request.form.get("edit_member_phone")
        edit_member_age = calculate_age(request.form.get("edit_member_age"))
        member_gender= request.form.get("edit_member_gender")
        edit_actual_starting_date=request.form.get("edit_actual_starting_date")
        edit_starting_date=request.form.get("edit_starting_date")
        user_input = request.form.get("edit_membership_packages")
        try:
            numeric_value, unit = user_input.split(maxsplit=1) if user_input else (None, None)
        except ValueError:
            numeric_value,unit=("wrong package","")
        member_End_date = calculate_end_date(edit_starting_date, numeric_value)
        member_membership_fees=membership_fees(user_input)
        member_membership_status=compare_dates(member_End_date)
        conn = sqlite3.connect('gym_system.db')
        cur = conn.cursor()
        cur.execute('UPDATE members SET name=?, email=?, phone=? ,age=? , gender=?,actual_starting_date=?,starting_date=?,End_date=?,membership_packages=? ,membership_fees=?, membership_status=?    WHERE id=?',
                (edit_member_name, edit_member_email, edit_member_phone,edit_member_age,member_gender,edit_actual_starting_date,
                edit_starting_date,member_End_date ,f"{numeric_value} {unit}",member_membership_fees,member_membership_status,member_id))
        conn.commit()
        conn.close()
        return redirect(url_for("index"))

#search by id route
@app.route("/show_member_data", methods=["POST"])
def show_member_data():
    if request.method == "POST":
        member_id = request.form.get("member_id")
        member_data = query_db('SELECT * FROM members WHERE id = ?', (member_id,), one=True)
        return render_template("show_member_data.html", member_data=member_data)
    return redirect(url_for("show_member_data"))

@app.route("/search_by_mobile_number", methods=["POST"])
def search_by_mobile_number():
    if request.method == "POST":
        member_phone = request.form.get("member_phone")
        member_data = query_db('SELECT * FROM members WHERE phone = ?', (member_phone,), one=True)
        return render_template("result_phone.html", member_data=member_data)
    return redirect(url_for("result_phone"))

@app.route("/result_phone", methods=["POST"])
def result_phone():
    if request.method == "POST":
        member_phone = request.form.get("member_phone")
        member_data = query_db('SELECT * FROM members WHERE phone = ?', (member_phone,), one=True)
        return render_template("result_phone.html", member_data=member_data)
    return redirect(url_for("result_phone"))

@app.route("/result", methods=["POST"])
def result():
    if request.method == "POST":
        member_name = request.form.get("member_name").capitalize()
        member_data = query_db('SELECT * FROM members WHERE name = ?', (member_name,), one=True)
        return render_template("result.html", member_data=member_data)
    return redirect(url_for("result"))

@app.route('/login', methods=['POST'])
def login_post():
    username = request.form['username']
    password = request.form['password']
    conn = sqlite3.connect('gym_system.db')
    cr = conn.cursor()
    cr.execute('''
        SELECT * FROM users
        WHERE username = ? 
    ''', (username,))
    result = cr.fetchone()
    conn.close()
    if result and result[3] == password:
        session['username'] = result[0]
        flash('success signup successful', 'success')
        return redirect(url_for('index', username=username))
    else:
        flash('error Incorrect username or password', 'error')
        return redirect(url_for('login'))
    
@app.route('/logout', methods=['GET', 'POST'])
def logout():
    # Clear the session data to log the user out
    session.clear()
    flash('success Logged out successfully', 'success')
    return render_template("logout.html")

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not username or not email or not password:
            flash('error All fields are required!', 'error')
            return render_template('signup.html')

        try:
            conn = get_db()
            cr = conn.cursor()
            cr.execute(
                'INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                (username, email, password)
            )
            conn.commit()
            flash('success User created successfully!', 'success')
            return redirect(url_for('login'))
        except sqlite3.IntegrityError:
            flash('error Username or email already exists!', 'error')
        except Exception as e:
            flash(f'error Server error: {str(e)}', 'error')
        finally:
            commit_close()

    return render_template('signup.html')

@app.route('/change_password', methods=['POST', 'GET'])
def change_password():
    if request.method == 'POST':
        username = request.form['username']
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        conn = get_db()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        user = cursor.fetchone()

        if user:
            app.logger.info(f"user: {user}")  # Debug print
            stored_password = user[3]  # Adjust the index based on your database structure
            app.logger.info(f"stored_password: {stored_password}")  # Debug print

            if old_password == stored_password:
                cursor.execute("UPDATE users SET password = ? WHERE username = ?", (new_password, username))
                commit_close()
                flash('success Password successfully changed!')
                return redirect(url_for('success'))
            else:
                error_message = "Invalid old password"
        else:
            error_message = "Invalid username"

        app.logger.error(f"Error changing password: {error_message}")  # Debug print
        return render_template('change_password.html', error_message=error_message)

    return render_template('change_password.html')

def update_attendance(member_id):
    global current_date,current_day,current_time
    member_data = get_member_data(member_id)
    if member_data:
        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_date = now.strftime("%Y-%m-%d")
        current_day = now.strftime("%A")

        query = "INSERT INTO attendance (num, id, name, end_date, membership_status, attendance_time, attendance_date, day) VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
        get_db().execute(query, (member_data['num'], member_data['id'], member_data['name'], member_data['end_date'],
                                member_data['membership_status'], current_time, current_date, current_day))
        get_db().commit()

def get_member_data(member_id):
    query = f"SELECT * FROM members WHERE id = {member_id}"
    return query_db(query, one=True)

@app.route('/attendance_table', methods=['GET', 'POST'])
def attendance_table():
    current_time = ""
    current_date = ""
    current_day = ""
    if request.method == 'POST':
        member_id = request.form.get('member_id')
        query = f"SELECT * FROM members WHERE id = {member_id}"
        cursor = get_db().cursor()
        cursor.execute(query)
        row = cursor.fetchone()
        

        if row:
            columns = [col[0] for col in cursor.description]
            member_data = dict(zip(columns, row))
            now = datetime.now()
            current_time = now.strftime("%H:%M:%S")
            current_date = now.strftime("%Y-%m-%d")
            current_day = now.strftime("%A")

            # Update or insert data into the first table (attendance)
            existing_data = query_db(f"SELECT * FROM attendance WHERE id = {member_data['id']}")
            if existing_data:
                update_query = f"UPDATE attendance SET name = '{member_data['name']}', " \
                                f"end_date = '{member_data['End_date']}', " \
                                f"membership_status = '{member_data['membership_status']}', " \
                                f"attendance_time = '{current_time}', " \
                                f"attendance_date = '{current_date}', " \
                                f"day = '{current_day}' WHERE id = {member_data['id']}"
                cursor.execute(update_query)
            else:
                insert_query = f"INSERT INTO attendance (id, name, end_date, membership_status, " \
                                f"attendance_time, attendance_date, day) VALUES ({member_data['id']}, " \
                                f"'{member_data['name']}', '{member_data['End_date']}', " \
                                f"'{member_data['membership_status']}', '{current_time}', " \
                                f"'{current_date}', '{current_day}')"
                cursor.execute(insert_query)

            # Insert data into the second table (attendance_backup)
            insert_query_backup = f"INSERT INTO attendance_backup (id, name, end_date, membership_status, " \
                                f"attendance_time, attendance_date, day) VALUES ({member_data['id']}, " \
                                f"'{member_data['name']}', '{member_data['End_date']}', " \
                                f"'{member_data['membership_status']}', '{current_time}', " \
                                f"'{current_date}', '{current_day}')"
            cursor.execute(insert_query_backup)

            get_db().commit()
            session.setdefault('members_data', []).append(member_data)
    
    all_attendance_data = query_db("SELECT * FROM attendance ORDER BY num asc", order_by=None)
    return render_template("attendance_table.html", members_data=all_attendance_data)

@app.route('/delete_all_data', methods=['POST'])
def delete_all_data():
    backup_query = "INSERT OR IGNORE INTO attendance_backup SELECT * FROM attendance"
    get_db().execute(backup_query)
    get_db().commit()
    delete_query = "DELETE FROM attendance"
    get_db().execute(delete_query)
    get_db().commit()
    return redirect(url_for('attendance_table'))

@app.route('/success')
def success():
    return render_template('success.html')

# في آخر الملف، بعد كل الروتس
with app.app_context():
    create_table()  # هتعمل الجداول أول مرة

with app.app_context():
    create_table()

# إغلاق الـ DB بعد كل طلب
@app.teardown_appcontext
def teardown_db(exception):
    close_db()  # ← دلوقتي هتعرفها
    

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False)











