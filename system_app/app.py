from flask import Flask, render_template, request, redirect, url_for, flash, session, g,jsonify
from datetime import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Also add this line to use DATABASE_URL
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
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# === Rino Only Decorator ===
def rino_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        if session.get('username') != 'rino':
            flash('You do not have permission to access this page!', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# @app.teardown_appcontext
# def teardown_db(exception):
#     close_db()

@app.route('/')
@app.route('/home')
@login_required
def index():
    # Don't do any flash here ever
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
            flash('All fields are required!', 'error')
            return render_template('login.html')
        
        try:
            user = query_db(
                'SELECT id, username, password FROM users WHERE username = %s',
                (username,), one=True
            )
            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                flash('Username or password is incorrect!', 'error')
        except Exception as e:
            flash(f'Database error: {str(e)}', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('Logout successful', 'success')
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
            flash('All fields are required!', 'error')
            return render_template('signup.html')
        
        # Validate password length
        if len(password) < 6:
            flash('Password must be at least 6 characters!', 'error')
            return render_template('signup.html')
        
        # Check if username already exists
        existing_username = query_db(
            'SELECT id FROM users WHERE username = %s',
            (username,), one=True
        )
        if existing_username:
            flash('Username already exists!', 'error')
            return render_template('signup.html')
        
        # Check if email already exists
        existing_email = query_db(
            'SELECT id FROM users WHERE email = %s',
            (email,), one=True
        )
        if existing_email:
            flash('Email already in use!', 'error')
            return render_template('signup.html')
        
        # Hash password and create user
        hashed_password = generate_password_hash(password)
        try:
            query_db(
                'INSERT INTO users (username, email, password) VALUES (%s, %s, %s)',
                (username, email, hashed_password), commit=True
            )
            flash('Account created successfully! Please log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            flash(f'Error: {str(e)}', 'error')
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
        # --- Get data ---
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

        # --- Calculations ---
        member_end_date = calculate_end_date(member_starting_date, numeric_value) or ""
        member_membership_fees = membership_fees(user_input)
        member_membership_status = compare_dates(member_end_date) or "Unknown"

        # --- 1. Check for duplicates ---
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

        # --- 2. Get last ID ---
        last_member = query_db('SELECT id FROM members ORDER BY id DESC LIMIT 1', one=True)
        new_member_id = (last_member['id'] + 1) if last_member else 1

        # --- 3. Add new member ---
        add_member(
            member_name, member_email, member_phone, member_age, member_gender,
            member_birthdate, member_actual_starting_date, member_starting_date,
            member_end_date, f"{numeric_value} {unit}", member_membership_fees,
            member_membership_status,
            custom_id=new_member_id
        )

        # --- Format date ---
        formatted_date = ""
        if member_actual_starting_date:
            try:
                parsed = datetime.strptime(member_actual_starting_date, "%Y-%m-%d")
                formatted_date = parsed.strftime("%d,%m,%Y")
            except:
                formatted_date = member_actual_starting_date

        # --- Success ---
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

# === Edit member ===
@app.route("/edit_member/<int:member_id>", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    if request.method == "GET":
        member = get_member(member_id)
        if not member:
            flash("Member not found!", "error")
            return redirect(url_for("index"))
        return render_template("edit_member.html", member=member)

    elif request.method == "POST":
        try:
            name = request.form.get("edit_member_name", "").capitalize()
            email = request.form.get("edit_member_email", "")
            phone = request.form.get("edit_member_phone", "")
            birthdate = request.form.get("edit_member_birthdate", "")
            age = calculate_age(birthdate)  # ← int always
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
            status = compare_dates(end_date) or "Unknown"

            update_member(member_id,
                name=name, email=email, phone=phone, age=age, gender=gender,
                birthdate=birthdate, actual_starting_date=actual_starting_date,
                starting_date=starting_date, end_date=end_date,
                membership_packages=f"{numeric_value} {unit}",
                membership_fees=fees, membership_status=status
            )
            flash("Member updated successfully!", "success")
        except Exception as e:
            flash(f"Error updating member: {str(e)}", "error")
        return redirect(url_for("index"))

@app.route("/show_member_data", methods=["POST"])
@login_required
def show_member_data():
    member_id = request.form.get("member_id", "")
    try:
        member_id = int(member_id)
    except:
        flash("Invalid member ID!", "error")
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
            flash('All fields are required!', 'error')
            return render_template('change_password.html')
        
        if new_password != confirm_password:
            flash('New passwords do not match!', 'error')
            return render_template('change_password.html')
        
        if len(new_password) < 6:
            flash('New password must be at least 6 characters!', 'error')
            return render_template('change_password.html')
        
        # Get user from session
        user_id = session.get('user_id')
        user = query_db('SELECT * FROM users WHERE id = %s', (user_id,), one=True)
        
        if user and check_password_hash(user['password'], old_password):
            query_db(
                'UPDATE users SET password = %s WHERE id = %s',
                (generate_password_hash(new_password), user_id), commit=True
            )
            flash('Password changed successfully!', 'success')
            return redirect(url_for('success'))
        else:
            flash('Old password is incorrect!', 'error')
    return render_template('change_password.html')


from datetime import datetime

from flask import g

@app.route('/attendance_table', methods=['GET', 'POST'])
@login_required
def attendance_table():
    if request.method == 'POST':
        member_id_str = request.form.get('member_id', '').strip()
        if not member_id_str.isdigit():
            flash("Enter a valid member ID!", "error")
        else:
            member_id = int(member_id_str)
            member = query_db(
                "SELECT name, end_date, membership_status FROM members WHERE id = %s", 
                (member_id,), one=True
            )

            if not member:
                flash(f"Member ID {member_id} not found!", "error")
            else:
                # Try to record attendance within try-except
                try:
                    # Make sure the member hasn't already been recorded today
                    today = datetime.now().strftime("%Y-%m-%d")
                    already = query_db(
                        "SELECT 1 FROM attendance WHERE member_id = %s AND attendance_date = %s", 
                        (member_id, today), one=True
                    )

                    if already:
                        flash(f"{member['name']} already came today!", "success")
                    else:
                        add_attendance(
                            member_id,
                            member['name'],
                            member['end_date'],
                            member['membership_status']
                        )
                        flash(f"Attendance for {member['name']} recorded successfully!", "success")

                except Exception as e:
                    print("Error adding attendance:", e)
                    # flash(f"Error recording attendance: {str(e)}", "error")

        data = query_db("SELECT * FROM attendance ORDER BY num ASC")
        return render_template("attendance_table.html", members_data=data)

    data = query_db("SELECT * FROM attendance ORDER BY num ASC")
    return render_template("attendance_table.html", members_data=data)




@app.route('/delete_all_data', methods=['POST'])
@login_required
def delete_all_data():
    try:
        print("\n--- DEBUG: Starting transfer and clear process ---")

        # Use one connection for all operations so TRUNCATE works
        conn = psycopg2.connect(DATABASE_URL, sslmode='require')
        cur = conn.cursor()
        
        try:
            # 1) Copy data to backup
            print("DEBUG: Copying data to attendance_backup...")
            cur.execute("""
                INSERT INTO attendance_backup 
                (member_id, name, end_date, membership_status, attendance_time, attendance_date, day)
                SELECT member_id, name, end_date, membership_status, attendance_time, attendance_date, day
                FROM attendance
            """)
            
            # 2) Clear table and reset numbering
            print("DEBUG: Clearing attendance table and resetting numbering...")
            cur.execute("TRUNCATE TABLE attendance RESTART IDENTITY")
            
            # Confirm operations
            conn.commit()
            print("--- Transfer and clear completed successfully! ---")
            
            flash("All attendance data moved to backup and table cleared successfully!", "success")

        except Exception as e:
            conn.rollback()
            print("===== Error during transfer or clear =====")
            import traceback
            traceback.print_exc()
            print("Error:", e)
            flash("An error occurred while clearing data! Check the console.", "error")
        
        finally:
            cur.close()
            conn.close()

    except Exception as e:
        print("===== Failed to connect to database =====")
        print(e)
        flash("Failed to connect to database!", "error")

    return redirect(url_for('attendance_table'))



@app.route('/attendance_backup', methods=['GET'])
@rino_required
def attendance_backup_table():
    try:
        # Pull all data from the backup table
        data = query_db("SELECT * FROM attendance_backup ORDER BY id ASC")
        return render_template("attendance_backup.html", backup_data=data)

    except Exception as e:
        import traceback
        traceback.print_exc()
        flash("An error occurred while loading the backup!", "error")
        return redirect(url_for('attendance_table'))







@app.route('/success')
@login_required
def success():
    return render_template('success.html')

@app.route('/send_email', methods=['GET', 'POST'])
@rino_required
def send_email():
    try:
        if request.method == 'POST':
            message = request.form.get('message', '').strip()
            
            if not message:
                flash('Message cannot be empty!', 'error')
                return render_template('send_email.html')
            
            try:
                # Get all member emails from database
                print("DEBUG: Querying database for member emails...")
                members = query_db('SELECT email, name FROM members WHERE email IS NOT NULL AND email != \'\'')
                
                # Debug: Check what we got
                print(f"DEBUG: Query returned: {type(members)}")
                print(f"DEBUG: Found {len(members) if members else 0} members with emails")
                if members and len(members) > 0:
                    print(f"DEBUG: First member: {members[0]}")
                    print(f"DEBUG: First member type: {type(members[0])}")
                    print(f"DEBUG: First member keys: {members[0].keys() if hasattr(members[0], 'keys') else 'N/A'}")
                
                if not members or len(members) == 0:
                    flash('No member emails found in the database!', 'error')
                    return render_template('send_email.html')
                
                # Email configuration
                sender_email = 'rival.gym1@gmail.com'
                sender_password = os.environ.get('GMAIL_APP_PASSWORD', '01147216302')
                
                if not sender_password:
                    flash('Email password not configured!', 'error')
                    return render_template('send_email.html')
                
                # Setup SMTP server - try both ports
                smtp_server = 'smtp.gmail.com'
                
                # Send email to each member
                sent_count = 0
                failed_emails = []
                server = None
                
                try:
                    print("DEBUG: Attempting to connect to SMTP server...")
                    # Try port 587 with STARTTLS first
                    try:
                        print("DEBUG: Trying port 587 with STARTTLS...")
                        server = smtplib.SMTP(smtp_server, 587, timeout=30)
                        server.starttls()
                        print("DEBUG: STARTTLS successful, logging in...")
                        server.login(sender_email, sender_password)
                        print("DEBUG: Successfully logged in via port 587")
                    except (smtplib.SMTPException, OSError, ConnectionError, Exception) as e:
                        print(f"DEBUG: Port 587 failed: {e}, trying port 465 with SSL...")
                        if server:
                            try:
                                server.quit()
                            except:
                                pass
                        # Fallback to port 465 with SSL
                        try:
                            import ssl
                            context = ssl.create_default_context()
                            server = smtplib.SMTP_SSL(smtp_server, 465, timeout=30, context=context)
                            print("DEBUG: SSL connection successful, logging in...")
                            server.login(sender_email, sender_password)
                            print("DEBUG: Successfully logged in via port 465")
                        except (OSError, ConnectionError) as ssl_error:
                            # Network is completely unreachable
                            error_msg = f'Cannot connect to Gmail SMTP server. Network error: {str(ssl_error)}. '
                            error_msg += 'This might be due to firewall restrictions or network configuration. '
                            error_msg += 'Please check your server\'s network settings or contact your hosting provider.'
                            print(f"CRITICAL: Both ports failed. Last error: {ssl_error}")
                            raise Exception(error_msg)
                    
                    for idx, member in enumerate(members):
                        recipient_email = None
                        try:
                            # Handle both dict and object access
                            if isinstance(member, dict):
                                recipient_email = member.get('email') or member.get('Email')
                            else:
                                recipient_email = getattr(member, 'email', None) or getattr(member, 'Email', None)
                            
                            if not recipient_email:
                                print(f"DEBUG: Member {idx} has no email field: {member}")
                                continue
                            
                            recipient_email = str(recipient_email).strip()
                            if not recipient_email:
                                continue
                                
                            print(f"DEBUG: Sending email {idx+1}/{len(members)} to {recipient_email}")
                            
                            # Create a new message for each recipient
                            msg = MIMEMultipart()
                            msg['From'] = sender_email
                            msg['To'] = recipient_email
                            msg['Subject'] = 'Message from Rival Gym'
                            msg.attach(MIMEText(message, 'plain'))
                            
                            server.sendmail(sender_email, recipient_email, msg.as_string())
                            sent_count += 1
                            print(f"DEBUG: Successfully sent to {recipient_email}")
                        except Exception as e:
                            email_addr = recipient_email if recipient_email else 'unknown'
                            print(f"ERROR: Failed to send email to {email_addr}: {e}")
                            import traceback
                            traceback.print_exc()
                            if recipient_email:
                                failed_emails.append(recipient_email)
                    
                    if server:
                        server.quit()
                    
                    if sent_count > 0:
                        success_msg = f'Message sent successfully to {sent_count} member(s)!'
                        if failed_emails:
                            success_msg += f' Failed to send to {len(failed_emails)} email(s).'
                        flash(success_msg, 'success')
                    else:
                        flash('Failed to send emails to all recipients!', 'error')
                        
                except smtplib.SMTPAuthenticationError as e:
                    error_msg = f'Email authentication failed: {str(e)}. Please check GMAIL_APP_PASSWORD.'
                    print(f"SMTP Auth Error: {e}")
                    import traceback
                    traceback.print_exc()
                    flash(error_msg, 'error')
                except (OSError, ConnectionError) as e:
                    error_msg = f'Network connection error: {str(e)}. '
                    error_msg += 'The server cannot reach Gmail\'s SMTP server. This might be due to: '
                    error_msg += '1) Firewall blocking outbound SMTP connections, '
                    error_msg += '2) Network configuration issues, or '
                    error_msg += '3) Server restrictions. Please contact your hosting provider or check firewall settings.'
                    print(f"Network Error: {e}")
                    import traceback
                    traceback.print_exc()
                    flash(error_msg, 'error')
                except smtplib.SMTPException as e:
                    error_msg = f'SMTP error occurred: {str(e)}'
                    print(f"SMTP Error: {e}")
                    import traceback
                    traceback.print_exc()
                    flash(error_msg, 'error')
                except Exception as e:
                    error_msg = f'Error sending emails: {str(e)}'
                    print(f"General SMTP Error: {e}")
                    import traceback
                    traceback.print_exc()
                    flash(error_msg, 'error')
                finally:
                    if server:
                        try:
                            server.quit()
                        except:
                            pass
                    
            except Exception as e:
                error_msg = f'Database error: {str(e)}'
                print(f"Database Error: {e}")
                import traceback
                traceback.print_exc()
                flash(error_msg, 'error')
        
        return render_template('send_email.html')
        
    except Exception as e:
        # Catch absolutely everything to prevent internal server error
        error_msg = f'Unexpected error: {str(e)}'
        print(f"CRITICAL ERROR in send_email: {e}")
        import traceback
        traceback.print_exc()
        flash(error_msg, 'error')
        return render_template('send_email.html')

# === Run application ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=True)

