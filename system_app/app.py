from flask import Flask, render_template, request, redirect, url_for, flash, session, g,jsonify
from datetime import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps

# وكمان أضف السطر ده عشان نستخدم DATABASE_URL
from system_app.queries import DATABASE_URL
from flask import session

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'my_secret_key_fallback')

from .func import calculate_age, calculate_end_date, membership_fees, compare_dates
from .queries import (
    create_table, query_db, check_name_exists, check_id_exists,
    add_member, get_member, update_member,
    add_attendance
)

with app.app_context():
    create_table()


# === Authentication Decorator ===
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('يجب تسجيل الدخول أولاً!', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# @app.teardown_appcontext
# def teardown_db(exception):
#     close_db()

@app.route('/')
@app.route('/home')
@login_required
def index():
    # ما تعملش أي flash هنا أبدًا
    attendance_data = query_db('SELECT * FROM attendance ORDER BY num ASC')
    members_data = query_db('SELECT * FROM members ORDER BY id DESC')
    return render_template("index.html", 
                        attendance_data=attendance_data, 
                        members_data=members_data)


@app.route('/login', methods=['GET', 'POST'])
def login():
    # If already logged in, redirect to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        if not username or not password:
            flash('جميع الحقول مطلوبة!', 'error')
            return render_template('login.html')
        
        try:
            user = query_db(
                'SELECT id, username, password FROM users WHERE username = %s',
                (username,), one=True
            )
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('تم تسجيل الدخول بنجاح!', 'success')
                return redirect(url_for('index'))
            else:
                flash('اسم المستخدم أو كلمة المرور غير صحيحة!', 'error')
        except Exception as e:
            flash(f'خطأ في الداتابيز: {str(e)}', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('تم تسجيل الخروج بنجاح', 'success')
    return redirect(url_for('login'))

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    # If already logged in, redirect to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')
        
        # Validate all fields
        if not all([username, email, password]):
            flash('جميع الحقول مطلوبة!', 'error')
            return render_template('signup.html')
        
        # Validate password length
        if len(password) < 6:
            flash('كلمة المرور يجب أن تكون 6 أحرف على الأقل!', 'error')
            return render_template('signup.html')
        
        # Check if username already exists
        existing_username = query_db(
            'SELECT id FROM users WHERE username = %s',
            (username,), one=True
        )
        if existing_username:
            flash('اسم المستخدم موجود بالفعل!', 'error')
            return render_template('signup.html')
        
        # Check if email already exists
        existing_email = query_db(
            'SELECT id FROM users WHERE email = %s',
            (email,), one=True
        )
        if existing_email:
            flash('البريد الإلكتروني مستخدم بالفعل!', 'error')
            return render_template('signup.html')
        
        # Hash password and create user
        hashed_password = generate_password_hash(password)
        try:
            query_db(
                'INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                (username, email, hashed_password), commit=True
            )
            flash('تم إنشاء الحساب بنجاح! يرجى تسجيل الدخول.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'خطأ: {str(e)}', 'error')
    return render_template('signup.html')

# @app.route("/home")
# def index():
#     attendance_data = query_db('SELECT * FROM attendance ORDER BY num ASC')
#     members_data = query_db('SELECT * FROM members ORDER BY id DESC')
#     return render_template("index.html", attendance_data=attendance_data, members_data=members_data)

@app.route('/search', methods=['GET', 'POST'])
@login_required
def search_by_name():
    if request.method == 'POST':
        name = request.form['name'].strip().capitalize()
        member = query_db('SELECT * FROM members WHERE name = %s', (name,), one=True)
        return render_template('result.html', name=name, data=member)
    return render_template('search.html')



@app.route("/add_member", methods=["POST"])
@login_required
def add_member_route():
    if request.method != "POST":
        return redirect(url_for("index"))

    try:
        # --- جلب البيانات ---
        member_name = request.form.get("member_name", "").strip().capitalize()
        if not member_name:
            flash("Member name is required!", "error")
            return redirect(url_for("index"))

        member_email = request.form.get("member_email", "").strip().lower()
        member_phone = request.form.get("member_phone", "").strip()
        birthdate_input = request.form.get("member_birthdate", "").strip()
        member_age = calculate_age(birthdate_input) if birthdate_input else None
        member_birthdate = birthdate_input
        member_gender = request.form.get("choice", "").strip()
        member_actual_starting_date = request.form.get("member_actual_starting_date", "").strip()
        member_starting_date = request.form.get("member_starting_date", "").strip()

        user_input = request.form.get("member_membership_packages", "").strip()
        numeric_value, unit = ("", "")
        if user_input:
            parts = user_input.split(maxsplit=1)
            numeric_value = parts[0]
            unit = parts[1] if len(parts) > 1 else ""

        # --- الحسابات ---
        member_end_date = calculate_end_date(member_starting_date, numeric_value) or ""
        member_membership_fees = membership_fees(user_input)
        member_membership_status = compare_dates(member_end_date) or "غير معروف"

        # --- 1. فحص التكرار ---
        existing = query_db('''
            SELECT id FROM members 
            WHERE email = %s OR phone = %s
            LIMIT 1
        ''', (member_email, member_phone), one=True)

        if existing:
            flash(
                f"The member you tried to add is already a member. His ID is: <strong>{existing['id']}</strong>",
                "error"
            )
            return redirect(url_for("index"))

        # --- 2. جلب آخر ID ---
        last_member = query_db('SELECT id FROM members ORDER BY id DESC LIMIT 1', one=True)
        new_member_id = (last_member['id'] + 1) if last_member else 1

        # --- 3. إضافة العضو الجديد ---
        add_member(
            member_name, member_email, member_phone, member_age, member_gender,
            member_birthdate, member_actual_starting_date, member_starting_date,
            member_end_date, f"{numeric_value} {unit}", member_membership_fees,
            member_membership_status,
            custom_id=new_member_id
        )

        # --- تنسيق التاريخ ---
        formatted_date = ""
        if member_actual_starting_date:
            try:
                parsed = datetime.strptime(member_actual_starting_date, "%Y-%m-%d")
                formatted_date = parsed.strftime("%d,%m,%Y")
            except:
                formatted_date = member_actual_starting_date

        # --- نجاح ---
        flash("Member added successfully!", "success")
        return redirect(url_for("add_member_done", 
                                new_member_id=new_member_id, 
                                formatted_date=formatted_date))

    except Exception as e:
        flash(f"Error: {str(e)}", "error")
        return redirect(url_for("index"))
    
    
    
    
@app.route("/add_member_done")
@login_required
def add_member_done():
    new_member_id = request.args.get('new_member_id')
    formatted_date = request.args.get('formatted_date')
    return render_template("add_member_done.html", 
                        new_member_id=new_member_id, 
                        formatted_date=formatted_date)
    
    
    
    

@app.route("/all_members")
@login_required
def all_members():
    members_data = query_db('SELECT * FROM members ORDER BY id ASC')
    return render_template("all_members.html", members_data=members_data)

# === تعديل عضو ===
@app.route("/edit_member/<int:member_id>", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    if request.method == "GET":
        member = get_member(member_id)
        if not member:
            flash("العضو غير موجود!", "error")
            return redirect(url_for("index"))
        return render_template("edit_member.html", member=member)

    elif request.method == "POST":
        try:
            name = request.form.get("edit_member_name", "").capitalize()
            email = request.form.get("edit_member_email", "")
            phone = request.form.get("edit_member_phone", "")
            birthdate = request.form.get("edit_member_birthdate", "")
            age = calculate_age(birthdate)  # ← int دايمًا
            gender = request.form.get("edit_member_gender", "")
            actual_starting_date = request.form.get("edit_actual_starting_date", "")
            starting_date = request.form.get("edit_starting_date", "")
            user_input = request.form.get("edit_membership_packages", "")
            numeric_value, unit = ("", "")
            if user_input:
                try:
                    parts = user_input.split(maxsplit=1)
                    numeric_value = parts[0]
                    unit = parts[1] if len(parts) > 1 else ""
                except:
                    pass
            end_date = calculate_end_date(starting_date, numeric_value) or ""
            fees = membership_fees(user_input)
            status = compare_dates(end_date) or "غير معروف"

            update_member(member_id,
                name=name, email=email, phone=phone, age=age, gender=gender,
                birthdate=birthdate, actual_starting_date=actual_starting_date,
                starting_date=starting_date, end_date=end_date,
                membership_packages=f"{numeric_value} {unit}",
                membership_fees=fees, membership_status=status
            )
            flash("تم تعديل العضو بنجاح!", "success")
        except Exception as e:
            flash(f"خطأ في التعديل: {str(e)}", "error")
        return redirect(url_for("index"))

@app.route("/show_member_data", methods=["POST"])
@login_required
def show_member_data():
    member_id = request.form.get("member_id", "")
    try:
        member_id = int(member_id)
    except:
        flash("رقم العضو غير صحيح!", "error")
        return redirect(url_for("index"))
    member_data = get_member(member_id)
    return render_template("show_member_data.html", member_data=member_data)

@app.route("/search_by_mobile_number", methods=["POST"])
@login_required
def search_by_mobile_number():
    phone = request.form.get("member_phone", "").strip()
    member_data = query_db('SELECT * FROM members WHERE phone = %s', (phone,), one=True)
    return render_template("result_phone.html", member_data=member_data)

@app.route("/result_phone", methods=["POST"])
@login_required
def result_phone():
    return search_by_mobile_number()

@app.route("/result", methods=["POST"])
@login_required
def result():
    name = request.form.get("member_name", "").strip().capitalize()
    member_data = query_db('SELECT * FROM members WHERE name = %s', (name,), one=True)
    return render_template("result.html", member_data=member_data)

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        old_password = request.form.get('old_password', '')
        new_password = request.form.get('new_password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not all([old_password, new_password, confirm_password]):
            flash('جميع الحقول مطلوبة!', 'error')
            return render_template('change_password.html')
        
        if new_password != confirm_password:
            flash('كلمة المرور الجديدة غير متطابقة!', 'error')
            return render_template('change_password.html')
        
        if len(new_password) < 6:
            flash('كلمة المرور الجديدة يجب أن تكون 6 أحرف على الأقل!', 'error')
            return render_template('change_password.html')
        
        # Get user from session
        user_id = session.get('user_id')
        user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
        
        if user and check_password_hash(user['password'], old_password):
            query_db(
                'UPDATE users SET password = %s WHERE id = %s',
                (generate_password_hash(new_password), user_id), commit=True
            )
            flash('تم تغيير كلمة المرور بنجاح!', 'success')
            return redirect(url_for('success'))
        else:
            flash('كلمة المرور القديمة غير صحيحة!', 'error')
    return render_template('change_password.html')


from datetime import datetime

from flask import g

@app.route('/attendance_table', methods=['GET', 'POST'])
@login_required
def attendance_table():
    if request.method == 'POST':
        member_id_str = request.form.get('member_id', '').strip()
        if not member_id_str.isdigit():
            flash("ادخل رقم عضو صحيح!", "error")
        else:
            member_id = int(member_id_str)
            member = query_db(
                "SELECT name, end_date, membership_status FROM members WHERE id = %s", 
                (member_id,), one=True
            )

            if not member:
                flash(f"العضو رقم {member_id} غير موجود!", "error")
            else:
                # نحاول نسجل الحضور ضمن try-except
                try:
                    # نتأكد أن العضو لم يتم تسجيل حضوره اليوم بالفعل
                    today = datetime.now().strftime("%Y-%m-%d")
                    already = query_db(
                        "SELECT 1 FROM attendance WHERE member_id = %s AND attendance_date = %s", 
                        (member_id, today), one=True
                    )

                    if already:
                        flash(f"{member['name']} جه النهاردة بالفعل!", "success")
                    else:
                        add_attendance(
                            member_id,
                            member['name'],
                            member['end_date'],
                            member['membership_status']
                        )
                        flash(f"تم تسجيل حضور {member['name']} بنجاح!", "success")

                except Exception as e:
                    print("Error adding attendance:", e)
                    # flash(f"حصل خطأ أثناء تسجيل الحضور: {str(e)}", "error")

        data = query_db("SELECT * FROM attendance ORDER BY num ASC")
        return render_template("attendance_table.html", members_data=data)

    data = query_db("SELECT * FROM attendance ORDER BY num ASC")
    return render_template("attendance_table.html", members_data=data)




@app.route('/delete_all_data', methods=['POST'])
@login_required
def delete_all_data():
    try:
        print("\n--- DEBUG: بدء عملية النقل والتفريغ ---")

        # نستخدم connection واحد لكل العمليات عشان TRUNCATE يشتغل
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        try:
            # 1) نسخ البيانات إلى النسخ الاحتياطي
            print("DEBUG: نسخ البيانات إلى attendance_backup...")
            cur.execute("""
                INSERT INTO attendance_backup 
                (member_id, name, end_date, membership_status, attendance_time, attendance_date, day)
                SELECT member_id, name, end_date, membership_status, attendance_time, attendance_date, day
                FROM attendance
            """)
            
            # 2) تفريغ الجدول وإعادة الترقيم
            print("DEBUG: تفريغ جدول attendance وإعادة الترقيم...")
            cur.execute("TRUNCATE TABLE attendance RESTART IDENTITY")
            
            # تأكيد العمليات
            conn.commit()
            print("--- تم النقل والتفريغ بنجاح! ---")
            
            flash("تم نقل جميع بيانات الحضور إلى النسخ الاحتياطي وتفريغ الجدول بنجاح!", "success")

        except Exception as e:
            conn.rollback()
            print("===== خطأ أثناء النقل أو التفريغ =====")
            import traceback
            traceback.print_exc()
            print("Error:", e)
            flash("حدث خطأ أثناء تفريغ البيانات! راجع الكونسول.", "error")
        
        finally:
            cur.close()
            conn.close()

    except Exception as e:
        print("===== فشل في الاتصال بالداتابيز =====")
        print(e)
        flash("فشل في الاتصال بقاعدة البيانات!", "error")

    return redirect(url_for('attendance_table'))



@app.route('/attendance_backup', methods=['GET'])
@login_required
def attendance_backup_table():
    try:
        # هنسحب كل الداتا من جدول النسخة الاحتياطية
        data = query_db("SELECT * FROM attendance_backup ORDER BY id ASC")
        return render_template("attendance_backup.html", backup_data=data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        flash("حدث خطأ أثناء تحميل النسخة الاحتياطية!", "error")
        return redirect(url_for('attendance_table'))







@app.route('/success')
@login_required
def success():
    return render_template('success.html')

# === تشغيل التطبيق ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

