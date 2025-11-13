from flask import Flask, render_template, request, redirect, url_for, flash, session, g
from datetime import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash

# === إنشاء الـ app أول حاجة ===
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'my secret key')

# === الـ imports من المجلدات ===
from .func import get_age_and_dob, add_member, calculate_age, calculate_end_date, membership_fees, compare_dates
from .queries import create_table, query_db, check_name_exists, check_id_exists, get_db, close_db

# === إنشاء الجداول عند بدء التطبيق ===
with app.app_context():
    create_table()

# === إغلاق الـ DB بعد كل طلب ===
@app.teardown_appcontext
def teardown_db(exception):
    close_db()

# ====================== الروتس ======================

@app.route('/')
def home():
    return "التطبيق شغال 100% يا وحش!"

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        try:
            # جيب البيانات كـ dict مش tuple
            user = query_db(
                'SELECT id, username, password FROM users WHERE username = %s', 
                (username,), 
                one=True
            )
            
            # تأكد إن user موجود ومش None
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Invalid username or password!', 'error')
                
        except Exception as e:
            flash(f'DB Error: {str(e)}', 'error')
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('success Logged out successfully', 'success')
    return render_template('logout.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        if not all([username, email, password]):
            flash('error All fields are required!', 'error')
            return render_template('signup.html')

        hashed_password = generate_password_hash(password)

        try:
            query_db(
                'INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                (username, email, hashed_password),
                commit=True
            )
            flash('success User created successfully!', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'error {str(e)}', 'error')

    return render_template('signup.html')

@app.route("/home")
def index():
    attendance_data = query_db('SELECT * FROM attendance ORDER BY num ASC')
    members_data = query_db('SELECT * FROM members')
    return render_template("index.html", attendance_data=attendance_data, members_data=members_data)

@app.route('/search', methods=['GET', 'POST'])
def search_by_name():
    if request.method == 'POST':
        name = request.form['name'].capitalize()
        member = query_db('SELECT * FROM members WHERE name = %s', (name,), one=True)
        return render_template('result.html', name=name, data=member)
    return render_template('search.html')

# from datetime import datetime
# from flask import request, redirect, url_for, flash

@app.route("/add_member", methods=["POST"])
def add_member_route():
    if request.method != "POST":
        return redirect(url_for("index"))

    try:
        # --- جلب البيانات بأمان ---
        member_name = request.form.get("member_name", "").strip().capitalize()
        if not member_name:
            flash("الاسم مطلوب!", "error")
            return redirect(url_for("add_member"))

        member_email = request.form.get("member_email", "").strip()
        member_phone = request.form.get("member_phone", "").strip()

        # تاريخ الميلاد
        birthdate_input = request.form.get("member_birthdate", "").strip()
        member_age = calculate_age(birthdate_input) if birthdate_input else None
        member_birthdate = birthdate_input

        member_gender = request.form.get("choice", "").strip()
        member_actual_starting_date = request.form.get("member_actual_starting_date", "").strip()
        member_starting_date = request.form.get("member_starting_date", "").strip()

        # الباقة
        user_input = request.form.get("member_membership_packages", "").strip()
        numeric_value, unit = ("", "")
        if user_input:
            try:
                parts = user_input.split(maxsplit=1)
                numeric_value = parts[0]
                unit = parts[1] if len(parts) > 1 else ""
            except:
                numeric_value, unit = ("", "")

        # --- حساب التواريخ والرسوم ---
        try:
            member_End_date = calculate_end_date(member_starting_date, numeric_value) or ""
        except:
            member_End_date = ""

        try:
            member_membership_fees = float(membership_fees(user_input) or 0)
        except:
            member_membership_fees = 0.0

        try:
            member_membership_status = compare_dates(member_End_date) or "غير معروف"
        except:
            member_membership_status = "غير معروف"

        # --- إضافة العضو ---
        try:
            new_member_id = add_member(
                member_name, member_email, member_phone, member_age, member_gender,
                member_birthdate, member_actual_starting_date, member_starting_date,
                member_End_date, f"{numeric_value} {unit}", member_membership_fees,
                member_membership_status
            )
        except Exception as e:
            flash(f"فشل في إضافة العضو: {str(e)}", "error")
            return redirect(url_for("add_member"))

        # --- تنسيق التاريخ ---
        formatted_date = ""
        if member_actual_starting_date:
            try:
                parsed = datetime.strptime(member_actual_starting_date, "%Y-%m-%d")
                formatted_date = parsed.strftime("%d,%m,%Y")
            except:
                formatted_date = member_actual_starting_date

        flash("تم إضافة العضو بنجاح!", "success")
        return redirect(url_for("add_member_done", new_member_id=new_member_id, formatted_date=formatted_date))

    except Exception as e:
        # أي خطأ عام → ارجع للنموذج
        flash(f"خطأ غير متوقع: {str(e)}", "error")
        return redirect(url_for("add_member"))

@app.route("/add_member_done/<int:new_member_id>")
def add_member_done(new_member_id):
    formatted_date = request.args.get("formatted_date", "")
    return render_template("add_member_done.html", 
                         new_member_id=new_member_id, 
                         formatted_date=formatted_date)

@app.route("/all_members")
def all_members():
    members_data = query_db('SELECT * FROM members')
    return render_template("all_members.html", members_data=members_data)

@app.route("/edit_member/<int:member_id>", methods=["GET", "POST"])
def edit_member(member_id):
    if request.method == "GET":
        member = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
        return render_template("edit_member.html", member=member)

    elif request.method == "POST":
        edit_member_name = request.form.get("edit_member_name", "").capitalize()
        edit_member_email = request.form.get("edit_member_email", "")
        edit_member_phone = request.form.get("edit_member_phone", "")
        edit_member_age = calculate_age(request.form.get("edit_member_age", ""))
        member_gender = request.form.get("edit_member_gender", "")
        edit_actual_starting_date = request.form.get("edit_actual_starting_date", "")
        edit_starting_date = request.form.get("edit_starting_date", "")
        user_input = request.form.get("edit_membership_packages", "")

        try:
            numeric_value, unit = user_input.split(maxsplit=1) if user_input else ("", "")
        except ValueError:
            numeric_value, unit = ("wrong", "")

        member_End_date = calculate_end_date(edit_starting_date, numeric_value)
        member_membership_fees = membership_fees(user_input)
        member_membership_status = compare_dates(member_End_date)

        query_db('''
            UPDATE members SET 
            name=%s, email=%s, phone=%s, age=%s, gender=%s,
            actual_starting_date=%s, starting_date=%s, End_date=%s,
            membership_packages=%s, membership_fees=%s, membership_status=%s
            WHERE id=%s
        ''', (
            edit_member_name, edit_member_email, edit_member_phone, edit_member_age, member_gender,
            edit_actual_starting_date, edit_starting_date, member_End_date,
            f"{numeric_value} {unit}", member_membership_fees, member_membership_status, member_id
        ), commit=True)

        return redirect(url_for("index"))

@app.route("/show_member_data", methods=["POST"])
def show_member_data():
    member_id = request.form.get("member_id", "")
    member_data = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
    return render_template("show_member_data.html", member_data=member_data)

@app.route("/search_by_mobile_number", methods=["POST"])
def search_by_mobile_number():
    member_phone = request.form.get("member_phone", "")
    member_data = query_db('SELECT * FROM members WHERE phone = %s', (member_phone,), one=True)
    return render_template("result_phone.html", member_data=member_data)

@app.route("/result_phone", methods=["POST"])
def result_phone():
    member_phone = request.form.get("member_phone", "")
    member_data = query_db('SELECT * FROM members WHERE phone = %s', (member_phone,), one=True)
    return render_template("result_phone.html", member_data=member_data)

@app.route("/result", methods=["POST"])
def result():
    member_name = request.form.get("member_name", "").capitalize()
    member_data = query_db('SELECT * FROM members WHERE name = %s', (member_name,), one=True)
    return render_template("result.html", member_data=member_data)

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if request.method == 'POST':
        username = request.form['username']
        old_password = request.form['old_password']
        new_password = request.form['new_password']

        user = query_db('SELECT * FROM users WHERE username = %s', (username,), one=True)
        if user and check_password_hash(user['password'], old_password):
            query_db(
                'UPDATE users SET password = %s WHERE username = %s',
                (generate_password_hash(new_password), username),
                commit=True
            )
            flash('success Password changed successfully!', 'success')
            return redirect(url_for('success'))
        else:
            flash('error Invalid username or old password!', 'error')

    return render_template('change_password.html')

@app.route('/attendance_table', methods=['GET', 'POST'])
def attendance_table():
    if request.method == 'POST':
        member_id_str = request.form.get('member_id', '')
        try:
            member_id = int(member_id_str)
        except ValueError:
            flash('error Invalid ID!', 'error')
            all_attendance_data = query_db("SELECT * FROM attendance ORDER BY num ASC")
            return render_template("attendance_table.html", members_data=all_attendance_data)

        member = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
        if not member:
            flash('error Member not found!', 'error')
            all_attendance_data = query_db("SELECT * FROM attendance ORDER BY num ASC")
            return render_template("attendance_table.html", members_data=all_attendance_data)

        now = datetime.now()
        current_time = now.strftime("%H:%M:%S")
        current_date = now.strftime("%Y-%m-%d")
        current_day = now.strftime("%A")

        existing = query_db('SELECT 1 FROM attendance WHERE id = %s', (member_id,), one=True)

        if existing:
            query_db('''
                UPDATE attendance SET
                name=%s, end_date=%s, membership_status=%s,
                attendance_time=%s, attendance_date=%s, day=%s
                WHERE id=%s
            ''', (
                member['name'], member['End_date'], member['membership_status'],
                current_time, current_date, current_day, member_id
            ), commit=True)
        else:
            query_db('''
                INSERT INTO attendance (id, name, end_date, membership_status,
                attendance_time, attendance_date, day)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            ''', (
                member_id, member['name'], member['End_date'], member['membership_status'],
                current_time, current_date, current_day
            ), commit=True)

        # Backup
        query_db('''
            INSERT INTO attendance_backup (id, name, end_date, membership_status,
            attendance_time, attendance_date, day)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        ''', (
            member_id, member['name'], member['End_date'], member['membership_status'],
            current_time, current_date, current_day
        ), commit=True)

        flash('success Attendance updated!', 'success')

    all_attendance_data = query_db("SELECT * FROM attendance ORDER BY num ASC")
    return render_template("attendance_table.html", members_data=all_attendance_data)

@app.route('/delete_all_data', methods=['POST'])
def delete_all_data():
    query_db("INSERT OR IGNORE INTO attendance_backup SELECT * FROM attendance", commit=True)
    query_db("DELETE FROM attendance", commit=True)
    return redirect(url_for('attendance_table'))

@app.route('/success')
def success():
    return render_template('success.html')

# === تشغيل التطبيق ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)



