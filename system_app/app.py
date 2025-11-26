from flask import Flask, render_template, request, redirect, url_for, flash, session, g,jsonify
from flask_wtf.csrf import CSRFProtect, CSRFError
from datetime import datetime, timedelta
import os
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import pool
from functools import wraps
from email_validator import validate_email, EmailNotValidError
import re
import secrets

app = Flask(__name__)

# Security: Use strong secret key from environment (required in production)
secret_key = os.environ.get('SECRET_KEY')
if not secret_key:
    secret_key = secrets.token_hex(32)
    print("WARNING: SECRET_KEY not set in environment. Using generated key (not secure for production!)")
app.secret_key = secret_key

# Enable CSRF protection
csrf = CSRFProtect(app)

# Secure session configuration
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('FLASK_ENV') == 'production'  # HTTPS only in production
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)  # 24 hour session timeout

# Security headers
@app.after_request
def set_security_headers(response):
    """Add security headers to all responses"""
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'SAMEORIGIN'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

# === Global Error Handlers for Debugging ===
@app.before_request
def log_request_info():
    """Log request information for debugging"""
    try:
        print(f"\n{'='*80}")
        print(f"REQUEST: {request.method} {request.path}")
        print(f"Remote Addr: {request.remote_addr}")
        print(f"User Agent: {request.headers.get('User-Agent', 'Unknown')}")
        if request.method == 'POST':
            print(f"Form Data Keys: {list(request.form.keys())}")
        print(f"{'='*80}\n")
    except Exception as e:
        print(f"Error in log_request_info: {e}")

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 Internal Server Errors with detailed logging"""
    import traceback
    error_trace = traceback.format_exc()
    
    print(f"\n{'='*80}")
    print("INTERNAL SERVER ERROR (500)")
    print(f"{'='*80}")
    print(f"Error Type: {type(error).__name__}")
    print(f"Error Message: {str(error)}")
    print(f"\nFull Traceback:")
    print(error_trace)
    print(f"{'='*80}\n")
    
    # Try to get more context
    try:
        print(f"Request Method: {request.method}")
        print(f"Request Path: {request.path}")
        print(f"Request URL: {request.url}")
        if request.method == 'POST':
            print(f"Form Data: {dict(request.form)}")
    except:
        pass
    
    # Return user-friendly error page
    return render_template('error.html', 
                          error_code=500,
                          error_message="An internal server error occurred. Please check the console logs for details."), 500

@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found Errors"""
    print(f"404 Error: {request.path}")
    return render_template('error.html', 
                          error_code=404,
                          error_message="The page you're looking for doesn't exist."), 404

@app.errorhandler(Exception)
def handle_exception(e):
    """Catch all unhandled exceptions"""
    import traceback
    error_trace = traceback.format_exc()
    
    print(f"\n{'='*80}")
    print("UNHANDLED EXCEPTION")
    print(f"{'='*80}")
    print(f"Exception Type: {type(e).__name__}")
    print(f"Exception Message: {str(e)}")
    print(f"\nFull Traceback:")
    print(error_trace)
    print(f"{'='*80}\n")
    
    # Try to get request context
    try:
        print(f"Request Method: {request.method if request else 'N/A'}")
        print(f"Request Path: {request.path if request else 'N/A'}")
    except:
        pass
    
    # Return 500 error page
    return render_template('error.html', 
                          error_code=500,
                          error_message=f"An error occurred: {str(e)}"), 500

@app.errorhandler(CSRFError)
def handle_csrf_error(e):
    """Handle CSRF token errors"""
    print(f"CSRF Error: {e.description}")
    flash('CSRF token missing or invalid. Please try again.', 'error')
    return redirect(request.url or url_for('index'))

from .func import calculate_age, calculate_end_date, membership_fees, compare_dates, calculate_invitations
from .queries import (
    DATABASE_URL, create_table, query_db, check_name_exists, check_id_exists,
    add_member, get_member, update_member, delete_member,
    add_attendance, get_all_logs, get_member_logs, log_action, get_undoable_actions, mark_action_undone, get_action_by_id,
    use_invitation, get_all_invitations, get_member_invitations,
    add_supplement, get_supplement, get_all_supplements, update_supplement, delete_supplement,
    add_supplement_sale, get_supplement_sales, get_supplement_statistics
)
from .queries import delete_all_data as delete_all_data_from_db

# Initialize database tables on startup
with app.app_context():
    try:
        create_table()
    except Exception as e:
        print(f"Warning: Could not create tables on startup: {e}")
        print("Tables may already exist or database connection failed.")


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
    try:
        # Limit to recent 50 records for performance
        attendance_data = query_db('SELECT * FROM attendance ORDER BY num DESC LIMIT 50')
        members_data = query_db('SELECT * FROM members ORDER BY id DESC LIMIT 50')
        return render_template("index.html", 
                                attendance_data=attendance_data or [], 
                                members_data=members_data or [])
    except Exception as e:
        print(f"Error in index route: {e}")
        import traceback
        traceback.print_exc()
        # Return empty data instead of crashing
        return render_template("index.html", 
                            attendance_data=[], 
                            members_data=[])


# Rate limiting for login (simple in-memory implementation)
_login_attempts = {}
_MAX_LOGIN_ATTEMPTS = 5
_LOGIN_LOCKOUT_TIME = timedelta(minutes=15)

def check_rate_limit(ip_address):
    """Check if IP is rate limited"""
    now = datetime.now()
    if ip_address in _login_attempts:
        attempts, lockout_until = _login_attempts[ip_address]
        if lockout_until and now < lockout_until:
            return False, f"Too many login attempts. Please try again after {lockout_until.strftime('%H:%M:%S')}"
        # Reset if lockout expired
        if lockout_until and now >= lockout_until:
            del _login_attempts[ip_address]
    return True, None

def record_failed_login(ip_address):
    """Record a failed login attempt"""
    now = datetime.now()
    if ip_address not in _login_attempts:
        _login_attempts[ip_address] = [1, None]
    else:
        attempts, _ = _login_attempts[ip_address]
        attempts += 1
        if attempts >= _MAX_LOGIN_ATTEMPTS:
            lockout_until = now + _LOGIN_LOCKOUT_TIME
            _login_attempts[ip_address] = [attempts, lockout_until]
        else:
            _login_attempts[ip_address] = [attempts, None]

def clear_login_attempts(ip_address):
    """Clear login attempts on successful login"""
    if ip_address in _login_attempts:
        del _login_attempts[ip_address]

@app.route('/login', methods=['GET', 'POST'])
@csrf.exempt  # Exempt login from CSRF (public endpoint, no authenticated session yet)
def login():
    # If already logged in, redirect to index
    if 'user_id' in session:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        # Get client IP for rate limiting
        ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
        if isinstance(ip_address, str) and ',' in ip_address:
            ip_address = ip_address.split(',')[0].strip()
        
        # Check rate limit
        allowed, error_msg = check_rate_limit(ip_address)
        if not allowed:
            flash(error_msg, 'error')
            return render_template('login.html')
        
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        
        # Input validation
        if not username or not password:
            flash('All fields are required!', 'error')
            return render_template('login.html')
        
        # Sanitize username (alphanumeric and underscore only)
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash('Invalid username format!', 'error')
            record_failed_login(ip_address)
            return render_template('login.html')
        
        # Limit input length
        if len(username) > 50 or len(password) > 200:
            flash('Input too long!', 'error')
            record_failed_login(ip_address)
            return render_template('login.html')
        
        try:
            user = query_db(
                'SELECT id, username, password, email_verified FROM users WHERE username = %s',
                (username,), one=True
            )
            # Fix: check_password_hash takes (hash, password) not (password, hash)
            if user and check_password_hash(user['password'], password):
                # Email verification is now optional (auto-verified on signup)
                # No need to check email_verified anymore
                
                session['user_id'] = user['id']
                session['username'] = user['username']
                session.permanent = True  # Enable permanent session
                clear_login_attempts(ip_address)
                flash('Login successful!', 'success')
                return redirect(url_for('index'))
            else:
                record_failed_login(ip_address)
                flash('Username or password is incorrect!', 'error')
        except Exception as e:
            print(f"Login error: {e}")
            flash('Database error. Please try again later.', 'error')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    session.clear()
    flash('Logout successful', 'success')
    return redirect(url_for('login'))

def validate_strong_password(password):
    """Validate password strength - must have uppercase, lowercase, number, and special char"""
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character (!@#$%^&*)"
    return True, "Password is strong"


@app.route('/signup', methods=['GET', 'POST'])
@csrf.exempt  # Exempt signup from CSRF (public endpoint)
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
        
        # Validate username format
        if not re.match(r'^[a-zA-Z0-9_]+$', username):
            flash('Username can only contain letters, numbers, and underscores!', 'error')
            return render_template('signup.html')
        
        if len(username) < 3 or len(username) > 30:
            flash('Username must be between 3 and 30 characters!', 'error')
            return render_template('signup.html')
        
        # Validate email format
        try:
            validation = validate_email(email)
            email = validation.email
        except EmailNotValidError as e:
            flash(f'Invalid email address: {str(e)}', 'error')
            return render_template('signup.html')
        
        # Validate strong password
        is_valid, error_msg = validate_strong_password(password)
        if not is_valid:
            flash(error_msg, 'error')
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
        
        # Generate verification token
        verification_token = secrets.token_urlsafe(32)
        token_expires = datetime.now() + timedelta(hours=24)
        
        # Hash password and create user
        hashed_password = generate_password_hash(password)
        try:
            query_db(
                'INSERT INTO users (username, email, password, email_verified, verification_token, token_expires) VALUES (%s, %s, %s, %s, %s, %s)',
                (username, email, hashed_password, False, verification_token, token_expires), commit=True
            )
            
            # Auto-verify email (no email sending)
            query_db(
                'UPDATE users SET email_verified = TRUE WHERE id = (SELECT id FROM users WHERE username = %s ORDER BY id DESC LIMIT 1)',
                (username,), commit=True
            )
            
            flash('Account created successfully! You can now log in.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            print(f"Error creating user: {e}")
            flash(f'Error creating account: {str(e)}', 'error')
    return render_template('signup.html')

@app.route('/verify_email/<token>')
def verify_email(token):
    """Verify user email with token"""
    try:
        # Find user with this token
        user = query_db(
            'SELECT id, username, email_verified, token_expires FROM users WHERE verification_token = %s',
            (token,), one=True
        )
        
        if not user:
            return render_template('verify_email.html', success=False, error_message='Invalid verification token.')
        
        # Check if already verified
        if user.get('email_verified', False):
            return render_template('verify_email.html', success=True, error_message='Email already verified.')
        
        # Check if token expired
        token_expires = user.get('token_expires')
        if token_expires:
            if datetime.now() > token_expires:
                # Generate new token
                new_token = secrets.token_urlsafe(32)
                new_expires = datetime.now() + timedelta(hours=24)
                query_db(
                    'UPDATE users SET verification_token = %s, token_expires = %s WHERE id = %s',
                    (new_token, new_expires, user['id']), commit=True
                )
                # Auto-verify since we're not sending emails
                query_db(
                    'UPDATE users SET email_verified = TRUE, verification_token = NULL, token_expires = NULL WHERE id = %s',
                    (user['id'],), commit=True
                )
                return render_template('verify_email.html', success=True, error_message='Verification link expired. Your account has been automatically verified.')
        
        # Verify email
        query_db(
            'UPDATE users SET email_verified = TRUE, verification_token = NULL, token_expires = NULL WHERE id = %s',
            (user['id'],), commit=True
        )
        
        return render_template('verify_email.html', success=True)
    except Exception as e:
        print(f"Error verifying email: {e}")
        return render_template('verify_email.html', success=False, error_message='An error occurred during verification.')

@app.route('/resend_verification', methods=['GET', 'POST'])
@csrf.exempt  # Exempt from CSRF (public endpoint)
def resend_verification():
    """Resend verification email to user"""
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        
        if not email:
            flash('Email address is required!', 'error')
            return render_template('resend_verification.html')
        
        try:
            # Validate email
            validation = validate_email(email)
            email = validation.email
        except EmailNotValidError as e:
            flash(f'Invalid email address: {str(e)}', 'error')
            return render_template('resend_verification.html')
        
        # Find user by email
        user = query_db(
            'SELECT id, username, email_verified, verification_token, token_expires FROM users WHERE email = %s',
            (email,), one=True
        )
        
        if not user:
            flash('No account found with this email address.', 'error')
            return render_template('resend_verification.html')
        
        # Check if already verified
        if user.get('email_verified', False):
            flash('This email is already verified. You can log in now.', 'success')
            return redirect(url_for('login'))
        
        # Generate new token
        verification_token = secrets.token_urlsafe(32)
        token_expires = datetime.now() + timedelta(hours=24)
        
        # Update user with new token
        query_db(
            'UPDATE users SET verification_token = %s, token_expires = %s WHERE id = %s',
            (verification_token, token_expires, user['id']), commit=True
        )
        
        # Auto-verify since we're not sending emails
        query_db(
            'UPDATE users SET email_verified = TRUE, verification_token = NULL, token_expires = NULL WHERE id = %s',
            (user['id'],), commit=True
        )
        
        flash('Your email has been verified! You can now log in.', 'success')
        return redirect(url_for('login'))
    
    return render_template('resend_verification.html')

# @app.route("/home")
# def index():
#     attendance_data = query_db('SELECT * FROM attendance ORDER BY num ASC')
#     members_data = query_db('SELECT * FROM members ORDER BY id DESC')
#     return render_template("index.html", attendance_data=attendance_data, members_data=members_data)

@app.route('/search', methods=['GET', 'POST'])
@login_required
def search_by_name():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Please enter a name to search!', 'error')
            return render_template('search.html')
        try:
            # Use ILIKE for case-insensitive partial matching
            member = query_db('SELECT * FROM members WHERE name ILIKE %s', (f'%{name}%',), one=True)
            return render_template('result.html', member_data=member)
        except Exception as e:
            print(f"Error in search_by_name route: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error searching for member: {str(e)}", "error")
            return render_template('search.html')
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
        member_invitations = calculate_invitations(user_input)

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
        added_id = add_member(
            member_name, member_email, member_phone, member_age, member_gender,
            member_birthdate, member_actual_starting_date, member_starting_date,
            member_end_date, f"{numeric_value} {unit}", member_membership_fees,
            member_membership_status,
            custom_id=new_member_id,
            invitations=member_invitations
        )
        
        # Log the addition action for undo
        username = session.get('username', 'Unknown')
        import json
        member_data = {
            'name': member_name,
            'email': member_email,
            'phone': member_phone,
            'age': member_age,
            'gender': member_gender,
            'birthdate': member_birthdate,
            'actual_starting_date': member_actual_starting_date,
            'starting_date': member_starting_date,
            'end_date': member_end_date,
            'membership_packages': f"{numeric_value} {unit}",
            'membership_fees': member_membership_fees,
            'membership_status': member_membership_status,
            'invitations': member_invitations
        }
        log_action('add_member', member_id=added_id, member_name=member_name,
                  action_data=member_data, performed_by=username)

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
    try:
        # Pagination: 50 items per page
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Get total count for pagination
        total_count = query_db('SELECT COUNT(*) as count FROM members', one=True)
        total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
        
        # Get paginated data
        members_data = query_db(
            'SELECT * FROM members ORDER BY id ASC LIMIT %s OFFSET %s',
            (per_page, offset)
        )
        
        return render_template("all_members.html", 
                            members_data=members_data or [],
                            page=page,
                            total_pages=total_pages,
                            total_count=total_count['count'] if total_count else 0)
    except Exception as e:
        print(f"Error in all_members route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading members: {str(e)}", "error")
        return render_template("all_members.html", members_data=[], page=1, total_pages=1, total_count=0)

# === Edit member ===
def format_date_for_input(date_str):
    """Convert date from various formats to YYYY-MM-DD for HTML date input"""
    if not date_str or date_str == 'None' or date_str == '':
        return ''
    
    try:
        from datetime import datetime
        
        # Try different date formats
        date_formats = [
            '%m/%d/%Y',           # mm/dd/yyyy (birthdate format)
            '%d/%m/%Y',           # dd/mm/yyyy (starting_date format)
            '%A, %B %d, %Y',      # Monday, November 25, 2025 (actual_starting_date format)
            '%Y-%m-%d',           # Already in correct format
            '%Y-%m-%d %H:%M:%S',  # With time
            '%m-%d-%Y',           # mm-dd-yyyy
            '%d-%m-%Y',           # dd-mm-yyyy
        ]
        
        for fmt in date_formats:
            try:
                dt = datetime.strptime(str(date_str).strip(), fmt)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue
        
        # If all formats fail, try to parse as-is
        print(f"Warning: Could not parse date format: {date_str}")
        return ''
    except Exception as e:
        print(f"Error formatting date {date_str}: {e}")
        return ''


@app.route("/edit_member/<int:member_id>", methods=["GET", "POST"])
@login_required
def edit_member(member_id):
    if request.method == "GET":
        try:
            member = get_member(member_id)
            if not member:
                flash("Member not found!", "error")
                return redirect(url_for("index"))
            
            # Format dates for HTML date input (YYYY-MM-DD format)
            # get_member returns a RealDictRow which is dict-like, but we'll convert to ensure we can modify
            if member:
                member_dict = dict(member) if hasattr(member, 'keys') else member
                member_dict['birthdate'] = format_date_for_input(member_dict.get('birthdate'))
                member_dict['actual_starting_date'] = format_date_for_input(member_dict.get('actual_starting_date'))
                member_dict['starting_date'] = format_date_for_input(member_dict.get('starting_date'))
                member = member_dict
            
            return render_template("edit_member.html", member=member)
        except Exception as e:
            print(f"Error in edit_member GET route: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error loading member: {str(e)}", "error")
            return redirect(url_for("index"))

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
            invitations = calculate_invitations(user_input)
            comment = request.form.get("edit_comment", "").strip()

            # Get username from session for logging
            username = session.get('username', 'Unknown')
            
            # Get old member data before update for undo
            old_member = get_member(member_id)
            if old_member:
                old_member_dict = dict(old_member)
                # Log the edit action for undo
                log_action('edit_member', member_id=member_id, member_name=old_member_dict.get('name'),
                          action_data={'old_values': old_member_dict}, performed_by=username)

            update_member(member_id,
                name=name, email=email, phone=phone, age=age, gender=gender,
                birthdate=birthdate, actual_starting_date=actual_starting_date,
                starting_date=starting_date, end_date=end_date,
                membership_packages=f"{numeric_value} {unit}",
                membership_fees=fees, membership_status=status,
                invitations=invitations, comment=comment,
                edited_by=username
            )
            flash("Member updated successfully!", "success")
        except Exception as e:
            flash(f"Error updating member: {str(e)}", "error")
        return redirect(url_for("index"))

@app.route("/delete_member/<int:member_id>", methods=["POST"])
@login_required
def delete_member_route(member_id):
    """Delete a member"""
    try:
        member = get_member(member_id)
        if not member:
            flash("Member not found!", "error")
            return redirect(url_for("all_members"))
        
        member_name = member.get('name', 'Unknown')
        username = session.get('username', 'Unknown')
        
        # Log the deletion action for undo
        import json
        member_data = dict(member)  # Convert to dict for JSON serialization
        log_action('delete_member', member_id=member_id, member_name=member_name, 
                  action_data=member_data, performed_by=username)
        
        delete_member(member_id)
        flash(f"Member {member_name} (ID: {member_id}) deleted successfully!", "success")
    except Exception as e:
        print(f"Error in delete_member route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error deleting member: {str(e)}", "error")
    return redirect(url_for("all_members"))

def calculate_freeze_period(package):
    """Calculate freeze period in days based on membership package"""
    if not package:
        return 0
    
    package_lower = str(package).lower().strip()
    
    # Extract number of months from package string
    import re
    month_match = re.search(r'(\d+)\s*(?:month|months|m)', package_lower)
    if month_match:
        months = int(month_match.group(1))
    else:
        # Check for year
        year_match = re.search(r'(\d+)\s*(?:year|years|y)', package_lower)
        if year_match:
            months = int(year_match.group(1)) * 12
        else:
            return 0
    
    # Freeze rules:
    # 1 month = 0 days
    # 2 months = 0 days
    # 3 months = 1 week (7 days)
    # 4 months = 1 week (7 days)
    # 6 months = 2 weeks (14 days)
    # 12 months = 1 month (30 days)
    
    if months == 1 or months == 2:
        return 0
    elif months == 3 or months == 4:
        return 7  # 1 week
    elif months == 6:
        return 14  # 2 weeks
    elif months == 12:
        return 30  # 1 month
    else:
        return 0

@app.route("/use_freeze/<int:member_id>", methods=["POST"])
@login_required
def use_freeze(member_id):
    try:
        member = get_member(member_id)
        if not member:
            flash("Member not found!", "error")
            return redirect(url_for("all_members"))
        
        # Check if freeze already used
        if member.get('freeze_used'):
            flash(f"Freeze has already been used for {member['name']}.", "error")
            return redirect(url_for("all_members"))
        
        # Calculate freeze period
        package = member.get('membership_packages', '')
        freeze_days = calculate_freeze_period(package)
        
        if freeze_days == 0:
            flash(f"No freeze available for {member['name']} (package: {package}).", "error")
            return redirect(url_for("all_members"))
        
        # Parse current end_date
        end_date_str = member.get('end_date', '')
        
        if not end_date_str or end_date_str == 'None':
            flash(f"No end date found for {member['name']}.", "error")
            return redirect(url_for("all_members"))
        
        # Try to parse the date in various formats
        end_date = None
        date_formats = [
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%d %H:%M:%S.%f',
            '%Y-%m-%d',
            '%m/%d/%Y %H:%M:%S',
            '%m/%d/%Y',
            '%d/%m/%Y %H:%M:%S',
            '%d/%m/%Y',
            '%B %d, %Y',
            '%b %d, %Y',
            '%d %B %Y',
            '%d %b %Y'
        ]
        
        for fmt in date_formats:
            try:
                end_date = datetime.strptime(str(end_date_str).strip(), fmt)
                break
            except:
                continue
        
        if not end_date:
            flash(f"Could not parse end date '{end_date_str}' for {member['name']}. Please check the date format.", "error")
            return redirect(url_for("all_members"))
        
        # Add freeze period to end_date
        new_end_date = end_date + timedelta(days=freeze_days)
        new_end_date_str = new_end_date.strftime('%Y-%m-%d %H:%M:%S')
        
        # Log the freeze action for undo
        username = session.get('username', 'Unknown')
        log_action('use_freeze', member_id=member_id, member_name=member['name'],
                  action_data={'old_end_date': end_date_str, 'new_end_date': new_end_date_str, 
                              'freeze_days': freeze_days, 'package': package},
                  performed_by=username)
        
        # Update member: extend end_date and mark freeze as used
        query_db(
            'UPDATE members SET end_date = %s, freeze_used = TRUE WHERE id = %s',
            (new_end_date_str, member_id),
            commit=True
        )
        
        flash(f"Freeze applied successfully! {member['name']}'s membership extended by {freeze_days} days. New end date: {new_end_date.strftime('%Y-%m-%d')}.", "success")
        return redirect(url_for("all_members"))
        
    except Exception as e:
        print(f"Error in use_freeze route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error applying freeze: {str(e)}", "error")
        return redirect(url_for("all_members"))

@app.route("/show_member_data", methods=["POST"])
@login_required
def show_member_data():
    member_id = request.form.get("member_id", "")
    try:
        member_id = int(member_id)
    except:
        flash("Invalid member ID!", "error")
        return redirect(url_for("index"))
    try:
        member_data = get_member(member_id)
        if not member_data:
            flash("Member not found!", "error")
            return redirect(url_for("index"))
        return render_template("show_member_data.html", member_data=member_data)
    except Exception as e:
        print(f"Error in show_member_data route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading member data: {str(e)}", "error")
        return redirect(url_for("index"))

@app.route("/search_by_mobile_number", methods=["POST"])
@login_required
def search_by_mobile_number():
    phone = request.form.get("member_phone", "").strip()
    try:
        member_data = query_db('SELECT * FROM members WHERE phone = %s', (phone,), one=True)
        return render_template("result_phone.html", member_data=member_data)
    except Exception as e:
        print(f"Error in search_by_mobile_number route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error searching for member: {str(e)}", "error")
        return render_template("result_phone.html", member_data=None)

@app.route("/result_phone", methods=["POST"])
@login_required
def result_phone():
    return search_by_mobile_number()

@app.route("/result", methods=["POST"])
@login_required
def result():
    name = request.form.get("member_name", "").strip()
    try:
        # Use ILIKE for case-insensitive partial matching
        member_data = query_db('SELECT * FROM members WHERE name ILIKE %s', (f'%{name}%',), one=True)
        return render_template("result.html", member_data=member_data)
    except Exception as e:
        print(f"Error in result route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error searching for member: {str(e)}", "error")
        return render_template("result.html", member_data=None)

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
        try:
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
        except Exception as e:
            print(f"Error in change_password route: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error changing password: {str(e)}", "error")
    return render_template('change_password.html')


@app.route('/attendance_table', methods=['GET', 'POST'])
@login_required
def attendance_table():
    if request.method == 'POST':
        member_id_str = request.form.get('member_id', '').strip()
        if not member_id_str.isdigit():
            flash("Enter a valid member ID!", "error")
        else:
            member_id = int(member_id_str)
            try:
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
                            # Log attendance addition for undo (before adding)
                            username = session.get('username', 'Unknown')
                            
                            # Add attendance
                            add_attendance(
                                member_id,
                                member['name'],
                                member['end_date'],
                                member['membership_status']
                            )
                            
                            # Get the attendance record that was just added
                            attendance_record = query_db(
                                'SELECT * FROM attendance WHERE member_id = %s AND attendance_date = %s ORDER BY num DESC LIMIT 1',
                                (member_id, today), one=True
                            )
                            if attendance_record:
                                log_action('add_attendance', member_id=member_id, member_name=member['name'],
                                          action_data={'attendance_num': attendance_record.get('num'),
                                                      'attendance_date': attendance_record.get('attendance_date'),
                                                      'attendance_time': attendance_record.get('attendance_time')},
                                          performed_by=username)
                            flash(f"Attendance for {member['name']} recorded successfully!", "success")
                    except Exception as e:
                        print("Error adding attendance:", e)
                        flash(f"Error recording attendance: {str(e)}", "error")
            except Exception as e:
                print(f"Error querying member in attendance_table: {e}")
                import traceback
                traceback.print_exc()
                flash(f"Error loading member: {str(e)}", "error")

        try:
            # Pagination: 50 items per page
            page = request.args.get('page', 1, type=int)
            per_page = 50
            offset = (page - 1) * per_page
            
            # Get total count for pagination
            total_count = query_db('SELECT COUNT(*) as count FROM attendance', one=True)
            total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
            
            # Get paginated data
            data = query_db("""
                SELECT a.*, m.comment 
                FROM attendance a 
                LEFT JOIN members m ON a.member_id = m.id 
                ORDER BY a.num ASC
                LIMIT %s OFFSET %s
            """, (per_page, offset))
            return render_template("attendance_table.html", 
                                members_data=data or [],
                                page=page,
                                total_pages=total_pages,
                                total_count=total_count['count'] if total_count else 0)
        except Exception as e:
            print(f"Error loading attendance data: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error loading attendance: {str(e)}", "error")
            return render_template("attendance_table.html", members_data=[], page=1, total_pages=1, total_count=0)

    try:
        # Pagination: 50 items per page
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Get total count for pagination
        total_count = query_db('SELECT COUNT(*) as count FROM attendance', one=True)
        total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
        
        # Get paginated data
        data = query_db("""
            SELECT a.*, m.comment 
            FROM attendance a 
            LEFT JOIN members m ON a.member_id = m.id 
            ORDER BY a.num ASC
            LIMIT %s OFFSET %s
        """, (per_page, offset))
        return render_template("attendance_table.html", 
                            members_data=data or [],
                            page=page,
                            total_pages=total_pages,
                            total_count=total_count['count'] if total_count else 0)
    except Exception as e:
        print(f"Error loading attendance data: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading attendance: {str(e)}", "error")
        return render_template("attendance_table.html", members_data=[])




@app.route('/delete_attendance_data', methods=['POST'])
@login_required
def delete_attendance_data():
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

@app.route('/invitations', methods=['GET', 'POST'])
@login_required
def invitations():
    """Handle invitation usage"""
    if request.method == 'POST':
        try:
            member_id_str = request.form.get('member_id', '').strip()
            friend_name = request.form.get('friend_name', '').strip().capitalize()
            friend_phone = request.form.get('friend_phone', '').strip()
            friend_email = request.form.get('friend_email', '').strip().lower()
            
            if not member_id_str or not friend_name or not friend_phone:
                flash('Member ID, friend name, and friend phone are required!', 'error')
                return redirect(url_for('invitations'))
            
            try:
                member_id = int(member_id_str)
            except ValueError:
                flash('Invalid member ID!', 'error')
                return redirect(url_for('invitations'))
            
            # Verify member exists
            member = get_member(member_id)
            if not member:
                flash(f'Member with ID {member_id} not found!', 'error')
                return redirect(url_for('invitations'))
            
            # Get username for logging
            username = session.get('username', 'Unknown')
            
            # Get old invitation count before using
            old_invitations = member.get('invitations', 0)
            
            # Use the invitation
            use_invitation(member_id, friend_name, friend_phone, friend_email, username)
            
            # Get the invitation record that was just created
            invitation_record = query_db(
                'SELECT * FROM invitations WHERE member_id = %s ORDER BY id DESC LIMIT 1',
                (member_id,), one=True
            )
            
            # Log invitation usage for undo
            log_action('use_invitation', member_id=member_id, member_name=member['name'],
                      action_data={'invitation_id': invitation_record.get('id') if invitation_record else None,
                                  'friend_name': friend_name,
                                  'friend_phone': friend_phone,
                                  'friend_email': friend_email,
                                  'old_invitations': old_invitations},
                      performed_by=username)
            
            flash(f'Invitation used successfully! {member["name"]} now has {member.get("invitations", 0) - 1} invitation(s) remaining.', 'success')
            return redirect(url_for('invitations'))
            
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('invitations'))
        except Exception as e:
            print(f"Error in invitations POST route: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error using invitation: {str(e)}", "error")
            return redirect(url_for('invitations'))
    
    # GET request - show invitations page
    try:
        # Pagination: 50 items per page
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Get total count for pagination
        total_count = query_db('SELECT COUNT(*) as count FROM invitations', one=True)
        total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
        
        # Get paginated invitations
        invitations_data = query_db(
            'SELECT * FROM invitations ORDER BY id ASC LIMIT %s OFFSET %s',
            (per_page, offset)
        )
        
        return render_template('invitations.html', 
                             invitations_data=invitations_data or [],
                             members_data=query_db('SELECT id, name, invitations FROM members ORDER BY id ASC') or [],
                             page=page,
                             total_pages=total_pages,
                             total_count=total_count['count'] if total_count else 0)
    except Exception as e:
        print(f"Error in invitations GET route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading invitations: {str(e)}", "error")
        return render_template('invitations.html', invitations_data=[], members_data=[], page=1, total_pages=1, total_count=0)

@app.route('/logs')
@login_required
def logs():
    """Display all member edit logs"""
    try:
        member_id = request.args.get('member_id', type=int)
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        if member_id:
            # Get total count for pagination
            total_count = query_db('SELECT COUNT(*) as count FROM member_logs WHERE member_id = %s', (member_id,), one=True)
            total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
            
            # Get paginated logs
            logs_data = query_db(
                'SELECT * FROM member_logs WHERE member_id = %s ORDER BY id ASC LIMIT %s OFFSET %s',
                (member_id, per_page, offset)
            )
            member = get_member(member_id)
            member_name = member['name'] if member else f"Member ID {member_id}"
        else:
            # Get total count for pagination
            total_count = query_db('SELECT COUNT(*) as count FROM member_logs', one=True)
            total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
            
            # Get paginated logs
            logs_data = query_db(
                'SELECT * FROM member_logs ORDER BY id ASC LIMIT %s OFFSET %s',
                (per_page, offset)
            )
            member_name = None
        
        return render_template('logs.html', 
                             logs_data=logs_data or [], 
                             member_id=member_id,
                             member_name=member_name,
                             page=page,
                             total_pages=total_pages,
                             total_count=total_count['count'] if total_count else 0)
    except Exception as e:
        print(f"Error in logs route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading logs: {str(e)}", "error")
        return render_template('logs.html', logs_data=[], member_id=None, member_name=None, page=1, total_pages=1, total_count=0)


@app.route('/undo')
@rino_required
def undo_page():
    """Display all undoable actions"""
    try:
        import json
        actions = get_undoable_actions(limit=200)
        # Parse action_data for each action to make it accessible in template
        parsed_actions = []
        for action in (actions or []):
            action_dict = dict(action) if hasattr(action, 'keys') else action
            action_data_raw = action_dict.get('action_data')
            if action_data_raw:
                if isinstance(action_data_raw, dict):
                    action_dict['action_data'] = action_data_raw
                elif isinstance(action_data_raw, str):
                    try:
                        action_dict['action_data'] = json.loads(action_data_raw)
                    except:
                        action_dict['action_data'] = {}
                else:
                    action_dict['action_data'] = {}
            else:
                action_dict['action_data'] = {}
            parsed_actions.append(action_dict)
        return render_template('undo.html', actions=parsed_actions)
    except Exception as e:
        print(f"Error in undo_page route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading undo page: {str(e)}", "error")
        return render_template('undo.html', actions=[])


@app.route('/undo_action/<int:action_id>', methods=['POST'])
@rino_required
def undo_action(action_id):
    """Undo a specific action"""
    try:
        import json
        action = get_action_by_id(action_id)
        if not action:
            flash("Action not found!", "error")
            return redirect(url_for('undo_page'))
        
        if action.get('undone'):
            flash("This action has already been undone!", "error")
            return redirect(url_for('undo_page'))
        
        action_type = action.get('action_type')
        # Handle action_data - it might be a dict (from JSONB) or a string
        action_data_raw = action.get('action_data')
        if action_data_raw is None:
            action_data = {}
        elif isinstance(action_data_raw, dict):
            action_data = action_data_raw
        elif isinstance(action_data_raw, str):
            action_data = json.loads(action_data_raw)
        else:
            action_data = {}
        member_id = action.get('member_id')
        member_name = action.get('member_name', 'Unknown')
        
        if action_type == 'delete_member':
            # Restore deleted member
            member_data = action_data
            add_member(
                member_data.get('name'),
                member_data.get('email'),
                member_data.get('phone'),
                member_data.get('age'),
                member_data.get('gender'),
                member_data.get('birthdate'),
                member_data.get('actual_starting_date'),
                member_data.get('starting_date'),
                member_data.get('end_date'),
                member_data.get('membership_packages'),
                member_data.get('membership_fees'),
                member_data.get('membership_status'),
                custom_id=member_id,
                invitations=member_data.get('invitations', 0),
                comment=member_data.get('comment')
            )
            flash(f"Member {member_name} (ID: {member_id}) restored successfully!", "success")
        
        elif action_type == 'use_freeze':
            # Undo freeze: restore original end_date and set freeze_used to FALSE
            old_end_date = action_data.get('old_end_date')
            query_db(
                'UPDATE members SET end_date = %s, freeze_used = FALSE WHERE id = %s',
                (old_end_date, member_id),
                commit=True
            )
            flash(f"Freeze undone for {member_name}. End date restored to {old_end_date}.", "success")
        
        elif action_type == 'add_member':
            # Delete the added member
            delete_member(member_id)
            flash(f"Member {member_name} (ID: {member_id}) removed successfully!", "success")
        
        elif action_type == 'edit_member':
            # Restore old member values
            old_values = action_data.get('old_values', {})
            if old_values:
                # Restore all old values
                update_member(member_id,
                    name=old_values.get('name'),
                    email=old_values.get('email'),
                    phone=old_values.get('phone'),
                    age=old_values.get('age'),
                    gender=old_values.get('gender'),
                    birthdate=old_values.get('birthdate'),
                    actual_starting_date=old_values.get('actual_starting_date'),
                    starting_date=old_values.get('starting_date'),
                    end_date=old_values.get('end_date'),
                    membership_packages=old_values.get('membership_packages'),
                    membership_fees=old_values.get('membership_fees'),
                    membership_status=old_values.get('membership_status'),
                    invitations=old_values.get('invitations', 0),
                    comment=old_values.get('comment'),
                    edited_by=session.get('username', 'System')
                )
                flash(f"Member {member_name} (ID: {member_id}) edit undone. All values restored.", "success")
            else:
                flash("Could not restore member edit - old values not found.", "error")
                return redirect(url_for('undo_page'))
        
        elif action_type == 'add_attendance':
            # Delete the attendance record
            attendance_num = action_data.get('attendance_num')
            if attendance_num:
                query_db('DELETE FROM attendance WHERE num = %s', (attendance_num,), commit=True)
                flash(f"Attendance record for {member_name} removed successfully!", "success")
            else:
                flash("Could not find attendance record to delete.", "error")
                return redirect(url_for('undo_page'))
        
        elif action_type == 'use_invitation':
            # Restore invitation: delete invitation record and restore invitation count
            invitation_id = action_data.get('invitation_id')
            old_invitations = action_data.get('old_invitations', 0)
            
            if invitation_id:
                # Delete the invitation record
                query_db('DELETE FROM invitations WHERE id = %s', (invitation_id,), commit=True)
                # Restore invitation count
                query_db('UPDATE members SET invitations = %s WHERE id = %s', 
                        (old_invitations, member_id), commit=True)
                flash(f"Invitation usage undone for {member_name}. Invitation count restored to {old_invitations}.", "success")
            else:
                flash("Could not find invitation record to restore.", "error")
                return redirect(url_for('undo_page'))
        
        else:
            flash(f"Unknown action type: {action_type}", "error")
            return redirect(url_for('undo_page'))
        
        # Mark action as undone
        mark_action_undone(action_id)
        return redirect(url_for('undo_page'))
        
    except Exception as e:
        print(f"Error in undo_action route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error undoing action: {str(e)}", "error")
        return redirect(url_for('undo_page'))


@app.route('/data_management', methods=['GET', 'POST'])
@rino_required
def data_management():
    """Page for deleting all data and importing Excel"""
    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'delete_all':
            try:
                delete_all_data_from_db()
                flash('All data deleted successfully! You can now import your Excel file.', 'success')
            except Exception as e:
                print(f"Error deleting all data: {e}")
                import traceback
                traceback.print_exc()
                flash(f'Error deleting all data: {str(e)}', 'error')
        
        elif action == 'import_excel':
            try:
                if 'excel_file' not in request.files:
                    flash('No file selected!', 'error')
                    return redirect(url_for('data_management'))
                
                file = request.files['excel_file']
                if file.filename == '':
                    flash('No file selected!', 'error')
                    return redirect(url_for('data_management'))
                
                if not (file.filename.endswith('.xlsx') or file.filename.endswith('.xls')):
                    flash('Please upload an Excel file (.xlsx or .xls)!', 'error')
                    return redirect(url_for('data_management'))
                
                # Read Excel file
                import pandas as pd
                import io
                
                print(f"Starting Excel import for file: {file.filename}")
                
                # Read the file with optimizations for large files
                file_content = file.read()
                # Use read_excel with optimizations for large files
                try:
                    # Try reading with engine='openpyxl' for better performance
                    df = pd.read_excel(io.BytesIO(file_content), engine='openpyxl')
                except:
                    # Fallback to default engine
                    df = pd.read_excel(io.BytesIO(file_content))
                
                # Limit to reasonable number of rows if file is extremely large
                max_rows = 10000  # Maximum rows to process
                if len(df) > max_rows:
                    flash(f'File has {len(df)} rows. Processing first {max_rows} rows only. Please split large files.', 'error')
                    df = df.head(max_rows)
                
                # Expected columns - exact mapping as specified by user
                # Map columns (case-insensitive, but preserve original case for matching)
                original_columns = df.columns.tolist()
                df.columns = df.columns.str.strip()  # Remove whitespace but keep case
                
                # Create mapping dictionary with exact column names from user's Excel
                column_mapping_exact = {
                    'id': ['id', 'ID'],
                    'name': ['Name', 'name', 'NAME'],
                    'date of birth': ['Date of Birth', 'date of birth', 'DATE OF BIRTH'],
                    'age': ['Age', 'age', 'AGE'],
                    'gender': ['Gender', 'gender', 'GENDER'],
                    'membership packages': ['Membership Packages', 'Membership packages', 'membership packages', 'MEMBERSHIP PACKAGES'],
                    'membership fees': ['Membership Fees', 'Membership fees', 'membership fees', 'MEMBERSHIP FEES'],
                    'actual starting date': ['Actual Starting Date', 'Actual starting date', 'actual starting date', 'ACTUAL STARTING DATE'],
                    'starting date': ['Starting Date', 'Starting date', 'starting date', 'STARTING DATE'],
                    'end date': ['End Date', 'End date', 'end date', 'END DATE'],
                    'status': ['Status', 'status', 'STATUS'],
                    'phone': ['Phone', 'phone', 'PHONE']
                }
                
                # Map columns (case-insensitive matching)
                mapped_columns = {}
                df_lower = df.columns.str.lower().str.strip()
                
                for target_col, possible_names in column_mapping_exact.items():
                    target_lower = target_col.lower().strip()
                    # Try exact match first
                    for orig_col in original_columns:
                        orig_col_clean = orig_col.strip()
                        orig_col_lower = orig_col_clean.lower()
                        
                        # Check if it matches any of the possible names (case-insensitive)
                        if orig_col_lower == target_lower:
                            mapped_columns[target_col] = orig_col_clean
                            break
                        # Also check if it's in the possible names list
                        for possible in possible_names:
                            if orig_col_lower == possible.lower().strip():
                                mapped_columns[target_col] = orig_col_clean
                                break
                        if target_col in mapped_columns:
                            break
                
                # Debug: Print what columns were found
                print(f"Excel columns found: {list(original_columns)}")
                print(f"Mapped columns: {mapped_columns}")
                
                # Verify required columns are found
                required_cols = ['name']
                missing_cols = [col for col in required_cols if col not in mapped_columns and 'name' not in [k.lower() for k in mapped_columns.keys()]]
                if missing_cols:
                    flash(f'Required column "Name" not found in Excel file. Found columns: {", ".join(original_columns)}', 'error')
                    return redirect(url_for('data_management'))
                
                # Import members in batches to handle large files
                imported = 0
                errors = []
                skipped = 0
                batch_size = 250  # Optimal batch size to prevent timeouts
                total_rows = len(df)
                
                print(f"Starting import of {total_rows} rows in batches of {batch_size}")
                # Flash initial message
                flash(f'Starting import of {total_rows} rows. This may take 10-15 minutes. Please wait and do not close this page...', 'success')
                
                # Import bulk_add_members function
                from system_app.queries import bulk_add_members
                
                # Process in batches to avoid memory/timeout issues
                for batch_start in range(0, total_rows, batch_size):
                    try:
                        batch_end = min(batch_start + batch_size, total_rows)
                        batch_df = df.iloc[batch_start:batch_end]
                        
                        batch_num = batch_start//batch_size + 1
                        total_batches = (total_rows + batch_size - 1) // batch_size
                        progress_pct = int((batch_num / total_batches) * 100)
                        print(f"Processing batch {batch_num}/{total_batches} ({progress_pct}%): rows {batch_start+1} to {batch_end}")
                        
                        # Log progress every 5 batches
                        if batch_num % 5 == 0 or batch_num == 1:
                            print(f"Progress: {progress_pct}% - Imported {imported} rows so far")
                        
                        # Collect all rows in this batch for bulk insert
                        batch_members = []
                        
                        for idx, row in batch_df.iterrows():
                            try:
                                # Extract data with defaults - using exact column mapping
                                # Name (required)
                                name_col = mapped_columns.get('name') or mapped_columns.get('Name')
                                if not name_col:
                                    # Try to find name column by checking all columns
                                    for col in original_columns:
                                        if col.lower().strip() == 'name':
                                            name_col = col
                                            break
                                
                                if not name_col:
                                    continue  # Skip if no name column found
                                
                                name = str(row.get(name_col, '')).strip() if name_col in row.index else ''
                                if not name or name == 'nan' or name == '':
                                    continue  # Skip rows without name
                                
                                # ID (optional - use as custom_id)
                                custom_id = None
                                id_col = mapped_columns.get('id') or mapped_columns.get('ID')
                                if id_col and id_col in row.index:
                                    try:
                                        id_val = row.get(id_col)
                                        if pd.notna(id_val):
                                            custom_id = int(float(id_val))
                                    except:
                                        pass
                                
                                # Phone
                                phone = None
                                phone_col = mapped_columns.get('phone') or mapped_columns.get('Phone')
                                if phone_col and phone_col in row.index:
                                    phone_val = row.get(phone_col)
                                    if pd.notna(phone_val):
                                        phone = str(phone_val).strip()
                                        if phone == 'nan' or phone == '' or phone.lower() == 'no number':
                                            phone = None
                                
                                # Age
                                age = None
                                age_col = mapped_columns.get('age') or mapped_columns.get('Age')
                                if age_col and age_col in row.index:
                                    try:
                                        age_val = row.get(age_col)
                                        if pd.notna(age_val):
                                            age = int(float(age_val))
                                    except:
                                        pass
                                
                                # Gender
                                gender = None
                                gender_col = mapped_columns.get('gender') or mapped_columns.get('Gender')
                                if gender_col and gender_col in row.index:
                                    gender_val = row.get(gender_col)
                                    if pd.notna(gender_val):
                                        gender = str(gender_val).strip()
                                        if gender == 'nan' or gender == '':
                                            gender = None
                                
                                # Date of Birth → birthdate
                                birthdate = None
                                dob_col = mapped_columns.get('date of birth') or mapped_columns.get('Date of Birth')
                                if dob_col and dob_col in row.index:
                                    try:
                                        birthdate_val = row.get(dob_col)
                                        if pd.notna(birthdate_val):
                                            if isinstance(birthdate_val, pd.Timestamp):
                                                birthdate = birthdate_val.strftime('%m/%d/%Y')
                                            else:
                                                birthdate = str(birthdate_val).strip()
                                                if birthdate == 'nan' or birthdate == '':
                                                    birthdate = None
                                    except Exception as e:
                                        print(f"Error processing birthdate: {e}")
                                
                                # Actual Starting Date → actual_starting_date
                                actual_starting_date = None
                                actual_start_col = mapped_columns.get('actual starting date') or mapped_columns.get('Actual Starting Date')
                                if actual_start_col and actual_start_col in row.index:
                                    try:
                                        actual_start_val = row.get(actual_start_col)
                                        if pd.notna(actual_start_val):
                                            if isinstance(actual_start_val, pd.Timestamp):
                                                actual_starting_date = actual_start_val.strftime('%A, %B %d, %Y')
                                            else:
                                                actual_starting_date = str(actual_start_val).strip()
                                                if actual_starting_date == 'nan' or actual_starting_date == '':
                                                    actual_starting_date = None
                                    except Exception as e:
                                        print(f"Error processing actual_starting_date: {e}")
                                
                                # Starting Date → starting_date
                                starting_date = None
                                start_col = mapped_columns.get('starting date') or mapped_columns.get('Starting Date')
                                if start_col and start_col in row.index:
                                    try:
                                        start_val = row.get(start_col)
                                        if pd.notna(start_val):
                                            if isinstance(start_val, pd.Timestamp):
                                                starting_date = start_val.strftime('%d/%m/%Y')
                                            else:
                                                starting_date = str(start_val).strip()
                                                if starting_date == 'nan' or starting_date == '':
                                                    starting_date = None
                                    except Exception as e:
                                        print(f"Error processing starting_date: {e}")
                                
                                # End Date → end_date
                                end_date = None
                                end_col = mapped_columns.get('end date') or mapped_columns.get('End Date')
                                if end_col and end_col in row.index:
                                    try:
                                        end_val = row.get(end_col)
                                        if pd.notna(end_val):
                                            if isinstance(end_val, pd.Timestamp):
                                                end_date = end_val.strftime('%d/%m/%Y')
                                            else:
                                                end_date = str(end_val).strip()
                                                if end_date == 'nan' or end_date == '':
                                                    end_date = None
                                    except Exception as e:
                                        print(f"Error processing end_date: {e}")
                                
                                # Membership Packages → membership_packages
                                membership_packages = None
                                packages_col = mapped_columns.get('membership packages') or mapped_columns.get('Membership Packages')
                                if packages_col and packages_col in row.index:
                                    packages_val = row.get(packages_col)
                                    if pd.notna(packages_val):
                                        membership_packages = str(packages_val).strip()
                                        if membership_packages == 'nan' or membership_packages == '':
                                            membership_packages = None
                                
                                # Membership Fees → membership_fees
                                membership_fees = None
                                fees_col = mapped_columns.get('membership fees') or mapped_columns.get('Membership Fees')
                                if fees_col and fees_col in row.index:
                                    try:
                                        fees_val = row.get(fees_col)
                                        if pd.notna(fees_val):
                                            membership_fees = float(fees_val)
                                    except Exception as e:
                                        print(f"Error processing membership_fees: {e}")
                                
                                # Status → membership_status
                                membership_status = None
                                status_col = mapped_columns.get('status') or mapped_columns.get('Status')
                                if status_col and status_col in row.index:
                                    status_val = row.get(status_col)
                                    if pd.notna(status_val):
                                        membership_status = str(status_val).strip()
                                        if membership_status == 'nan' or membership_status == '':
                                            membership_status = None
                                
                                # Email (optional - not in user's list but keep for compatibility)
                                email = None
                                
                                # Comment (optional - not in user's list but keep for compatibility)
                                comment = None
                                
                                # Calculate invitations if package is provided but invitations not set
                                invitations = 0
                                if membership_packages:
                                    invitations = calculate_invitations(membership_packages)
                                
                                # Add to batch list for bulk insert
                                if custom_id is not None:
                                    batch_members.append((
                                        custom_id, name, email, phone, age, gender, birthdate,
                                        actual_starting_date, starting_date, end_date,
                                        membership_packages, membership_fees, membership_status,
                                        invitations, comment
                                    ))
                                else:
                                    batch_members.append((
                                        name, email, phone, age, gender, birthdate,
                                        actual_starting_date, starting_date, end_date,
                                        membership_packages, membership_fees, membership_status,
                                        invitations, comment
                                    ))
                                
                            except Exception as e:
                                error_msg = str(e)
                                # Truncate long error messages
                                if len(error_msg) > 100:
                                    error_msg = error_msg[:100] + "..."
                                errors.append(f"Row {idx + 2}: {error_msg}")  # +2 because Excel rows start at 1 and we have header
                                print(f"Error processing row {idx + 2}: {e}")
                                # Continue processing next row even if this one fails
                                continue

                        # Bulk insert the entire batch at once
                        if batch_members:
                            try:
                                batch_imported = bulk_add_members(batch_members)
                                imported += batch_imported
                                print(f"Batch {batch_num}: Successfully imported {batch_imported} members")
                            except Exception as bulk_error:
                                print(f"Bulk insert failed for batch {batch_num}: {bulk_error}")
                                errors.append(f"Batch {batch_num} bulk insert failed: {str(bulk_error)[:100]}")
                                # Fall back to individual inserts for this batch
                                print(f"Falling back to individual inserts for batch {batch_num}...")
                                for member_data in batch_members:
                                    try:
                                        if len(member_data) == 15:  # Has custom_id
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
                                        else:  # No custom_id
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
                                        imported += 1
                                    except Exception as individual_error:
                                        errors.append(f"Row in batch {batch_num}: {str(individual_error)[:100]}")
                                continue
                                
                        # Log batch completion
                        if batch_num % 3 == 0:  # Log every 3 batches
                            progress = int((imported/total_rows)*100) if total_rows > 0 else 0
                            print(f"Batch {batch_num}/{total_batches} completed. Imported so far: {imported} rows ({progress}%)")
                        
                        # Small delay every 10 batches to prevent overwhelming
                        import time
                        if batch_num % 10 == 0:
                            time.sleep(0.1)  # Small delay
                        
                    except Exception as batch_error:
                        # If entire batch fails, log it but continue with next batch
                        print(f"ERROR in batch {batch_num}: {batch_error}")
                        errors.append(f"Batch {batch_num} (rows {batch_start+1}-{batch_end}): {str(batch_error)[:100]}")
                        # Continue to next batch
                        continue
                
                # Final summary
                print(f"Import completed. Total: {imported} imported, {len(errors)} errors, {total_rows - imported - len(errors)} skipped")
                
                if imported > 0:
                    success_msg = f'Successfully imported {imported} member(s) out of {total_rows} row(s)!'
                    if len(errors) > 0:
                        success_msg += f' ({len(errors)} row(s) had errors)'
                        flash(success_msg, 'success')
                
                if errors:
                    # Show summary of errors
                    error_count = len(errors)
                    if error_count <= 5:
                        error_msg = f'Errors in {error_count} row(s): ' + '; '.join(errors)
                    else:
                        error_msg = f'Errors in {error_count} row(s). First 5: ' + '; '.join(errors[:5]) + f' ... and {error_count - 5} more'
                    flash(error_msg, 'error')
                
            except Exception as e:
                print(f"CRITICAL ERROR importing Excel: {e}")
                import traceback
                error_trace = traceback.format_exc()
                print(error_trace)
                # Show user-friendly error message
                error_msg = f'Error importing Excel file: {str(e)}'
                if len(error_msg) > 200:
                    error_msg = error_msg[:200] + "..."
                    flash(error_msg, 'error')
                # Also log the full traceback for debugging
                print("Full error traceback:")
                print(error_trace)
        
        return redirect(url_for('data_management'))
    
    # GET request - show data management page
    try:
        member_count = query_db('SELECT COUNT(*) as count FROM members', one=True)
        attendance_count = query_db('SELECT COUNT(*) as count FROM attendance', one=True)
        return render_template('data_management.html',
                            member_count=member_count['count'] if member_count else 0,
                            attendance_count=attendance_count['count'] if attendance_count else 0)
    except Exception as e:
        print(f"Error in data_management route: {e}")
        import traceback
        traceback.print_exc()
        return render_template('data_management.html', member_count=0, attendance_count=0)
        return render_template('data_management.html', member_count=0, attendance_count=0)

@app.route('/offers', methods=['GET', 'POST'])
@login_required
def offers():
    """Page for creating and processing offers with AI"""
    if request.method == 'POST':
        try:
            offer_text = request.form.get('offer_text', '').strip()
            if not offer_text:
                flash('Please enter an offer description!', 'error')
                return render_template('offers.html', offer_data=None)
            
            # Process offer with AI
            structured_data = process_offer_with_ai(offer_text)
            
            if structured_data:
                return render_template('offers.html', offer_data=structured_data)
            else:
                flash('Failed to process offer. Please try again.', 'error')
                return render_template('offers.html', offer_data=None)
        except Exception as e:
            print(f"Error processing offer: {e}")
            import traceback
            traceback.print_exc()
            flash(f'Error processing offer: {str(e)}', 'error')
            return render_template('offers.html', offer_data=None)
    
    # GET request
    return render_template('offers.html', offer_data=None)


def process_offer_with_ai(offer_text):
    """Process offer text with OpenAI AI and return structured data - Enhanced with smarter AI"""
    try:
        # Try to import OpenAI
        try:
            import openai
        except ImportError:
            print("OpenAI library not installed. Falling back to pattern matching.")
            return process_offer_with_pattern_matching(offer_text)
        
        # Get OpenAI API key from environment
        api_key = os.environ.get('OPENAI_API_KEY')
        if not api_key:
            print("OPENAI_API_KEY not found in environment. Falling back to pattern matching.")
            return process_offer_with_pattern_matching(offer_text)
        
        # Initialize OpenAI client
        client = openai.OpenAI(api_key=api_key)
        
        # Enhanced, more intelligent prompt that understands context better
        system_prompt = """You are an expert business analyst specializing in gym and fitness center membership offers. 
Your task is to intelligently analyze offer descriptions and extract ALL relevant information with deep understanding of context.

You understand:
- Implied information (e.g., if price is mentioned without currency, infer from context)
- Relative dates (e.g., "end of month", "next week", "in 2 days")
- Discount calculations (if original and new price are mentioned)
- Membership tiers and what they typically include
- Common gym terminology and abbreviations
- Multiple offers in one text
- Hidden conditions or restrictions

Be thorough, accurate, and extract every piece of valuable information. Think like a human business analyst would."""

        user_prompt = f"""You are ChatGPT-level intelligent at extracting information. Read the text word-by-word and extract EXACTLY what is written.

OFFER TEXT TO ANALYZE:
"{offer_text}"

STEP-BY-STEP EXTRACTION PROCESS:

STEP 1 - FIND THE PRICE:
- Look for numbers followed by currency symbols ($, €, £, AED) OR numbers after words like "for", "price", "cost"
- Example: "for 1200$" → price is "1200" or "$1200"
- Example: "4 months for 1200" → price is "1200" 
- Example: "$500 membership" → price is "500" or "$500"
- CRITICAL: Extract the COMPLETE number. If you see "1200", extract "1200" NOT "120" or "4" or any partial number.
- If multiple numbers exist, the price is usually the LARGEST number or the number near "for"/"price"/"cost"

STEP 2 - FIND THE DURATION:
- Look for patterns like "X months", "X month", "X years", etc.
- Always use plural: "4 months" not "4 month"
- Example: "4 months" → duration: "4 months"

STEP 3 - FIND ELIGIBILITY:
- "for new members only" → "New Members Only"
- "for old members and new members" → "All Members" or "Old Members and New Members"
- "for old members" or "for existing members" → "Existing Members Only"
- "for new and old members" → "All Members"

STEP 4 - FIND VALIDITY:
- "until end of month" or "until this month end" → Calculate actual last day of current month
- "until [date]" → Use that exact date
- "valid until [date]" → Use that exact date

Now extract and return JSON with these fields:

{{
  "title": "Compelling title",
  "duration": "EXACT duration from text (e.g., '4 months')",
  "price": "EXACT price number from text (e.g., '1200' or '$1200') - MUST match what's in the text",
  "original_price": "Original price if discount mentioned",
  "discount_amount": "Discount amount if applicable",
  "discount_percentage": "Discount % if mentioned",
  "savings": "Customer savings",
  "features": ["List of features"],
  "number_of_sessions": "Number of PT sessions if mentioned",
  "session_duration": "Session duration",
  "valid_from": "Start date",
  "valid_until": "End date - calculate if 'end of month' mentioned",
  "eligibility": "EXACT eligibility from text",
  "offer_type": "Limited Time Offer" if has expiry, else "Standard Offer",
  "payment_options": "Payment plans",
  "restrictions": "Limitations",
  "terms_and_conditions": "Terms",
  "additional_benefits": "Extra perks",
  "cancellation_policy": "Cancellation terms",
  "description": "Summary",
  "target_audience": "Target group",
  "urgency_indicators": "Urgency cues",
  "comparison_value": "Value proposition"
}}

VERIFICATION CHECKLIST before returning:
✓ Price matches the number in the text (not a partial number)
✓ Duration is plural (e.g., "4 months" not "4 month")
✓ Eligibility matches what's written in text
✓ All numbers are complete, not partial

Return ONLY the JSON object, nothing else."""

        # Try GPT-4 first (smarter), fallback to GPT-3.5-turbo
        models_to_try = ["gpt-4", "gpt-4-turbo-preview", "gpt-3.5-turbo"]
        ai_response = None
        last_error = None
        
        for model in models_to_try:
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ],
                    temperature=0.2,  # Lower for more consistent, accurate extraction
                    max_tokens=1500,  # Increased for comprehensive extraction
                    response_format={"type": "json_object"}  # Force JSON output
                )
                ai_response = response.choices[0].message.content.strip()
                print(f"Successfully used model: {model}")
                break
            except Exception as e:
                last_error = e
                print(f"Model {model} failed, trying next...")
                continue
        
        if not ai_response:
            raise Exception(f"All models failed. Last error: {last_error}")
        
        # Parse JSON response
        import json
        # Remove markdown code blocks if present (though response_format should prevent this)
        if ai_response.startswith('```'):
            ai_response = ai_response.split('```')[1]
            if ai_response.startswith('json'):
                ai_response = ai_response[4:]
            ai_response = ai_response.strip()
        
        structured_offer = json.loads(ai_response)
        
        # Post-process and validate extracted data with AGGRESSIVE error correction
        import re
        from datetime import datetime, timedelta
        import calendar
        
        # AGGRESSIVE PRICE FIX - Extract directly from text if AI got it wrong
        if 'price' in structured_offer:
            price_str = str(structured_offer['price']).strip()
            # Remove currency symbols for comparison
            price_clean = re.sub(r'[\$€£AED\s]', '', price_str)
            
            # Find ALL numbers in the text
            numbers_in_text = re.findall(r'\d+', offer_text)
            
            # Try multiple patterns to find the price
            price_patterns = [
                r'(?:for|price|cost|pay|only)\s*(\d+)',
                r'(\d+)\s*\$',
                r'\$\s*(\d+)',
                r'(\d+)\s*(?:dollars|AED|euros|pounds)',
                r'(\d+)\s*(?:until|for|members)',
            ]
            
            extracted_price = None
            for pattern in price_patterns:
                match = re.search(pattern, offer_text, re.IGNORECASE)
                if match:
                    candidate = match.group(1)
                    # Prefer larger numbers (prices are usually larger than durations)
                    if not extracted_price or int(candidate) > int(extracted_price):
                        extracted_price = candidate
            
            # If we found a price in text
            if extracted_price:
                # If AI's price is wrong (too small, doesn't match, or is clearly wrong)
                if not price_clean or int(price_clean) != int(extracted_price):
                    if not price_clean or int(price_clean) < int(extracted_price) // 2:
                        print(f"Price correction: AI said '{price_str}' but text has '{extracted_price}', using text value")
                        structured_offer['price'] = extracted_price
            elif numbers_in_text:
                # If AI price is clearly wrong (like "$4" when text has "1200"), use largest number
                largest_num = max(numbers_in_text, key=int)
                if not price_clean or (price_clean.isdigit() and int(price_clean) < int(largest_num) // 5):
                    print(f"Price correction: AI said '{price_str}' but largest number in text is '{largest_num}', using it")
                    structured_offer['price'] = largest_num
        
        # Fix eligibility if it's wrong
        if 'eligibility' in structured_offer:
            eligibility_lower = str(structured_offer['eligibility']).lower()
            offer_lower = offer_text.lower()
            # Check if text mentions both old and new members
            if ('old' in offer_lower and 'new' in offer_lower) or ('existing' in offer_lower and 'new' in offer_lower):
                if 'all' not in eligibility_lower and 'both' not in eligibility_lower:
                    structured_offer['eligibility'] = "All Members (Old and New)"
        
        # Fix duration format (ensure plural)
        if 'duration' in structured_offer and structured_offer['duration']:
            duration = str(structured_offer['duration']).strip()
            # If it says "4 month" make it "4 months"
            if re.match(r'^\d+\s+month$', duration, re.IGNORECASE):
                structured_offer['duration'] = duration + 's'
        
        # Calculate end of month if mentioned
        if 'valid_until' in structured_offer:
            valid_until = str(structured_offer['valid_until']).lower()
            if 'end of month' in valid_until or 'month end' in valid_until or 'this month end' in valid_until:
                today = datetime.now()
                last_day = calendar.monthrange(today.year, today.month)[1]
                end_date = datetime(today.year, today.month, last_day)
                structured_offer['valid_until'] = end_date.strftime('%B %d, %Y')
        
        # Intelligent data cleaning and formatting
        cleaned_offer = {}
        for key, value in structured_offer.items():
            # Skip null values or convert them
            if value is None or value == "":
                continue  # Skip empty fields instead of showing "-"
            
            # Format key name (snake_case to Title Case)
            formatted_key = key.replace('_', ' ').title()
            
            # Handle different data types intelligently
            if isinstance(value, list):
                if len(value) > 0:
                    # Join list items with proper formatting
                    cleaned_offer[formatted_key] = ', '.join(str(v) for v in value if v)
            elif isinstance(value, (int, float)):
                # Format numbers appropriately
                if 'price' in key.lower() or 'amount' in key.lower() or 'savings' in key.lower():
                    # Don't add currency if it's already a clean number - let user see the number
                    cleaned_offer[formatted_key] = str(value)
                elif 'percentage' in key.lower() or 'discount' in key.lower():
                    cleaned_offer[formatted_key] = f"{value}%"
                else:
                    cleaned_offer[formatted_key] = str(value)
            elif isinstance(value, bool):
                cleaned_offer[formatted_key] = "Yes" if value else "No"
            else:
                # String values - clean them up
                str_value = str(value).strip()
                # Remove any weird characters that shouldn't be in prices
                if 'price' in key.lower() and str_value:
                    # If price has random letters, try to extract just the number
                    if re.search(r'[a-zA-Z]', str_value) and not any(c in str_value for c in ['$', '€', '£', 'AED']):
                        numbers = re.findall(r'\d+', str_value)
                        if numbers:
                            str_value = numbers[0]  # Take the first number found
                if str_value:
                    cleaned_offer[formatted_key] = str_value
        
        # If we got good data, return it
        if cleaned_offer:
            return [cleaned_offer]
        else:
            # If AI returned empty, fall back
            return process_offer_with_pattern_matching(offer_text)
        
    except json.JSONDecodeError as e:
        import json
        print(f"Error parsing AI JSON response: {e}")
        if 'ai_response' in locals() and ai_response:
            print(f"AI Response: {ai_response[:500]}...")  # Print first 500 chars
        # Fall back to pattern matching
        return process_offer_with_pattern_matching(offer_text)
    except Exception as e:
        print(f"Error in process_offer_with_ai: {e}")
        import traceback
        traceback.print_exc()
        # Fall back to pattern matching if OpenAI fails
        return process_offer_with_pattern_matching(offer_text)


def process_offer_with_pattern_matching(offer_text):
    """Fallback function using pattern matching when OpenAI is not available"""
    try:
        import json
        import re
        
        structured_offer = {}
        
        # Extract duration (e.g., "3 months", "6 months", "1 year")
        duration_match = re.search(r'(\d+)\s*(month|months|year|years|week|weeks)', offer_text, re.IGNORECASE)
        if duration_match:
            structured_offer['Duration'] = f"{duration_match.group(1)} {duration_match.group(2)}"
        
        # Extract price (e.g., "$300", "300 dollars", "AED 500")
        price_match = re.search(r'[\$€£AED]?\s*(\d+(?:\.\d+)?)', offer_text, re.IGNORECASE)
        if price_match:
            currency = re.search(r'[\$€£AED]', offer_text, re.IGNORECASE)
            currency_symbol = currency.group(0) if currency else '$'
            structured_offer['Price'] = f"{currency_symbol}{price_match.group(1)}"
        
        # Extract features/benefits
        features = []
        if re.search(r'personal training|pt session', offer_text, re.IGNORECASE):
            pt_match = re.search(r'(\d+)\s*(personal training|pt)', offer_text, re.IGNORECASE)
            if pt_match:
                features.append(f"{pt_match.group(1)} Personal Training Sessions")
            else:
                features.append("Personal Training Sessions")
        
        if re.search(r'nutrition|diet', offer_text, re.IGNORECASE):
            features.append("Nutrition Consultation")
        
        if re.search(r'gym access|access', offer_text, re.IGNORECASE):
            features.append("Full Gym Access")
        
        if features:
            structured_offer['Features'] = ', '.join(features)
        
        # Extract validity/expiry date
        date_patterns = [
            r'valid until (\w+ \d{1,2},? \d{4})',
            r'until (\w+ \d{1,2},? \d{4})',
            r'expires? (\w+ \d{1,2},? \d{4})',
            r'until (\d{1,2}/\d{1,2}/\d{4})',
            r'valid until (\d{1,2}-\d{1,2}-\d{4})',
        ]
        for pattern in date_patterns:
            date_match = re.search(pattern, offer_text, re.IGNORECASE)
            if date_match:
                structured_offer['Valid Until'] = date_match.group(1)
                break
        
        # Extract membership type
        if re.search(r'new member', offer_text, re.IGNORECASE):
            structured_offer['Eligibility'] = "New Members Only"
        elif re.search(r'existing member|current member', offer_text, re.IGNORECASE):
            structured_offer['Eligibility'] = "Existing Members Only"
        else:
            structured_offer['Eligibility'] = "All Members"
        
        # Extract offer type
        if re.search(r'special|promo|discount|deal', offer_text, re.IGNORECASE):
            structured_offer['Offer Type'] = "Special Promotion"
        else:
            structured_offer['Offer Type'] = "Standard Offer"
        
        # Add description
        structured_offer['Description'] = offer_text[:200] + ('...' if len(offer_text) > 200 else '')
        
        # Return as list of one item for table display
        return [structured_offer]
        
    except Exception as e:
        print(f"Error in process_offer_with_pattern_matching: {e}")
        import traceback
        traceback.print_exc()
        return None

@app.route('/supplements')
@login_required
def supplements():
    """Supplement and Water Management System"""
    try:
        supplements_data = get_all_supplements()
        stats = get_supplement_statistics()
        recent_sales = get_supplement_sales(limit=50)
        is_rino = session.get('username') == 'rino'
        return render_template('supplements.html', 
                             supplements=supplements_data or [],
                             stats=stats,
                             recent_sales=recent_sales or [],
                             is_rino=is_rino)
    except Exception as e:
        print(f"Error in supplements route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading supplements: {str(e)}", "error")
        return render_template('supplements.html', supplements=[], stats={}, recent_sales=[], is_rino=False)


@app.route('/add_supplement', methods=['POST'])
@rino_required
def add_supplement_route():
    """Add a new supplement/product"""
    try:
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip() or None
        subcategory = request.form.get('subcategory', '').strip() or None
        price = float(request.form.get('price', 0) or 0)
        cost = float(request.form.get('cost', 0) or 0)
        stock_quantity = int(request.form.get('stock_quantity', 0) or 0)
        unit = request.form.get('unit', 'piece').strip()
        description = request.form.get('description', '').strip() or None
        supplier = request.form.get('supplier', '').strip() or None
        barcode = request.form.get('barcode', '').strip() or None
        
        if not name:
            flash('Product name is required!', 'error')
            return redirect(url_for('supplements'))
        
        add_supplement(name, category, subcategory, price, cost, stock_quantity, unit, description, supplier, barcode)
        flash(f'Product "{name}" added successfully!', 'success')
    except Exception as e:
        print(f"Error adding supplement: {e}")
        flash(f'Error adding product: {str(e)}', 'error')
    return redirect(url_for('supplements'))


@app.route('/edit_supplement/<int:supplement_id>', methods=['POST'])
@rino_required
def edit_supplement(supplement_id):
    """Edit a supplement/product"""
    try:
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip() or None
        subcategory = request.form.get('subcategory', '').strip() or None
        price = float(request.form.get('price', 0) or 0)
        cost = float(request.form.get('cost', 0) or 0)
        stock_quantity = int(request.form.get('stock_quantity', 0) or 0)
        unit = request.form.get('unit', 'piece').strip()
        description = request.form.get('description', '').strip() or None
        supplier = request.form.get('supplier', '').strip() or None
        barcode = request.form.get('barcode', '').strip() or None
        
        if not name:
            flash('Product name is required!', 'error')
            return redirect(url_for('supplements'))
        
        update_supplement(supplement_id,
                         name=name, category=category, subcategory=subcategory,
                         price=price, cost=cost, stock_quantity=stock_quantity,
                         unit=unit, description=description, supplier=supplier, barcode=barcode)
        flash(f'Product "{name}" updated successfully!', 'success')
    except Exception as e:
        print(f"Error editing supplement: {e}")
        flash(f'Error updating product: {str(e)}', 'error')
    return redirect(url_for('supplements'))


@app.route('/delete_supplement/<int:supplement_id>', methods=['POST'])
@rino_required
def delete_supplement_route(supplement_id):
    """Delete a supplement/product"""
    try:
        supplement = get_supplement(supplement_id)
        if supplement:
            delete_supplement(supplement_id)
            flash(f'Product "{supplement["name"]}" deleted successfully!', 'success')
        else:
            flash('Product not found!', 'error')
    except Exception as e:
        print(f"Error deleting supplement: {e}")
        flash(f'Error deleting product: {str(e)}', 'error')
    return redirect(url_for('supplements'))


@app.route('/sell_supplement/<int:supplement_id>', methods=['POST'])
@login_required
def sell_supplement(supplement_id):
    """Record a supplement sale"""
    try:
        supplement = get_supplement(supplement_id)
        if not supplement:
            flash('Product not found!', 'error')
            return redirect(url_for('supplements'))
        
        quantity = int(request.form.get('quantity', 1) or 1)
        customer_name = request.form.get('customer_name', '').strip() or None
        payment_method = request.form.get('payment_method', 'cash').strip()
        sold_by = session.get('username', 'Unknown')
        
        if quantity <= 0:
            flash('Quantity must be greater than 0!', 'error')
            return redirect(url_for('supplements'))
        
        if supplement['stock_quantity'] < quantity:
            flash(f'Insufficient stock! Available: {supplement["stock_quantity"]}', 'error')
            return redirect(url_for('supplements'))
        
        unit_price = supplement['price']
        total_price = unit_price * quantity
        
        add_supplement_sale(supplement_id, supplement['name'], quantity, unit_price, total_price, sold_by, customer_name, payment_method)
        flash(f'Sale recorded: {quantity} x {supplement["name"]} = {total_price:.2f}', 'success')
    except Exception as e:
        print(f"Error selling supplement: {e}")
        flash(f'Error recording sale: {str(e)}', 'error')
    return redirect(url_for('supplements'))


@app.route('/api/supplement_stats')
@login_required
def supplement_stats_api():
    """API endpoint for supplement statistics (for AJAX updates)"""
    try:
        stats = get_supplement_statistics()
        return jsonify(stats)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# === Debug Route (for testing) ===
@app.route('/debug/test')
def debug_test():
    """Test route to verify the app is working"""
    try:
        return jsonify({
            'status': 'ok',
            'message': 'Application is running',
            'database_connected': bool(query_db('SELECT 1', one=True)),
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': str(e),
            'error_type': type(e).__name__
        }), 500

# === Run application ===
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    print(f"\n{'='*80}")
    print("Starting Flask Application...")
    print(f"Debug Mode: True")
    print(f"Port: {port}")
    print(f"{'='*80}\n")
    app.run(host='0.0.0.0', port=port, debug=True)

