from flask import Flask, render_template, request, redirect, url_for, flash, session, g, jsonify
from flask_wtf.csrf import CSRFProtect, CSRFError
from datetime import datetime, timedelta
import os
import json
from werkzeug.security import generate_password_hash, check_password_hash
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from psycopg2.extensions import register_adapter, AsIs
from psycopg2 import pool
from functools import wraps
from email_validator import validate_email, EmailNotValidError
import re
import secrets
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

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

@app.before_request
def track_user_activity():
    """Track active users for online status"""
    try:
        if 'user_id' in session:
            user_id = session['user_id']
            username = session.get('username', 'Unknown')
            now = datetime.now()
            
            # Get IP address
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
            if isinstance(ip_address, str) and ',' in ip_address:
                ip_address = ip_address.split(',')[0].strip()
            
            # Update or create user activity record
            if user_id not in _active_users:
                _active_users[user_id] = {
                    'username': username,
                    'login_time': now,
                    'last_activity': now,
                    'ip_address': ip_address
                }
            else:
                _active_users[user_id]['last_activity'] = now
                _active_users[user_id]['ip_address'] = ip_address
            
            # Clean up inactive users (older than timeout)
            inactive_users = []
            for uid, data in _active_users.items():
                if now - data['last_activity'] > _ACTIVITY_TIMEOUT:
                    inactive_users.append(uid)
            
            for uid in inactive_users:
                del _active_users[uid]
    except Exception as e:
        print(f"Error tracking user activity: {e}")

def scheduled_daily_status_update():
    """Scheduled task to update membership statuses daily at midnight"""
    with app.app_context():
        try:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled daily membership status update...")
            updated_count = update_all_membership_statuses()
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Daily status update completed. Updated {updated_count} member(s).")
        except Exception as e:
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error in scheduled status update: {e}")
            import traceback
            traceback.print_exc()

def get_online_users():
    """Get list of currently online users"""
    now = datetime.now()
    online_users = []
    
    # Clean up inactive users first
    inactive_users = []
    for user_id, data in _active_users.items():
        if now - data['last_activity'] > _ACTIVITY_TIMEOUT:
            inactive_users.append(user_id)
    
    for uid in inactive_users:
        del _active_users[uid]
    
    # Return active users
    for user_id, data in _active_users.items():
        time_online = now - data['login_time']
        time_since_activity = now - data['last_activity']
        online_users.append({
            'user_id': user_id,
            'username': data['username'],
            'login_time': data['login_time'],
            'last_activity': data['last_activity'],
            'ip_address': data['ip_address'],
            'time_online': time_online,
            'time_since_activity': time_since_activity
        })
    
    # Sort by last activity (most recent first)
    online_users.sort(key=lambda x: x['last_activity'], reverse=True)
    return online_users

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
    add_supplement_sale, get_supplement_sales, get_supplement_statistics,
    add_staff, get_staff, get_all_staff, update_staff, delete_staff,
    add_staff_purchase, get_staff_purchases, get_staff_statistics,
    log_renewal, get_renewal_logs, get_daily_totals, get_monthly_total,
    create_invoice, get_invoice, get_invoice_by_number, get_all_invoices
)
from .queries import delete_all_data as delete_all_data_from_db

# Initialize database tables on startup
with app.app_context():
    try:
        create_table()
    except Exception as e:
        print(f"Warning: Could not create tables on startup: {e}")
        print("Tables may already exist or database connection failed.")

# Initialize scheduler for daily status updates at midnight
scheduler = BackgroundScheduler(daemon=True)
scheduler.add_job(
    func=scheduled_daily_status_update,
    trigger=CronTrigger(hour=0, minute=0),  # Run at midnight (00:00) every day
    id='daily_status_update',
    name='Daily Membership Status Update',
    replace_existing=True
)
scheduler.start()
print("Scheduler started: Daily membership status update scheduled for 12:00 AM every day")

# Ensure scheduler shuts down when app stops
import atexit
atexit.register(lambda: scheduler.shutdown())


# === Authorization Helpers & Decorators ===

def _load_permissions(raw_permissions):
    """Safely load permissions from DB (JSONB or TEXT) into a dict."""
    if not raw_permissions:
        return {}
    if isinstance(raw_permissions, dict):
        return raw_permissions
    try:
        return json.loads(raw_permissions)
    except Exception:
        return {}


def get_default_permissions_for_username(username):
    """
    Default permission sets:
    - rino: super admin (access to everything)
    - ahmed_adel: everything except delete_member, undo_action, data_management,
                  online_users, training_templates, offers, renewal_log
    - malit_deng: everything except undo_action, data_management, online_users,
                  training_templates, offers, renewal_log, supplements_water,
                  attendance_backup, delete_member
    - others (new accounts): attendance only
    """
    username = (username or '').strip()

    # Super admin
    if username == 'rino':
        return {'super_admin': True}

    # Base full-access set
    base = {
        'index': True,
        'attendance': True,
        'members_view': True,
        'members_edit': True,
        'delete_member': True,
        'training_templates': True,
        'offers': True,
        'renewal_log': True,
        'supplements_water': True,
        'attendance_backup': True,
        'undo_action': True,
        'data_management': True,
        'online_users': True,
    }

    if username == 'ahmed_adel':
        perms = base.copy()
        perms.update({
            'delete_member': False,
            'undo_action': False,
            'data_management': False,
            'online_users': False,
            'training_templates': False,
            'offers': False,
            'renewal_log': False,
        })
        return perms

    if username == 'malit_deng':
        perms = base.copy()
        perms.update({
            'delete_member': False,
            'undo_action': False,
            'data_management': False,
            'online_users': False,
            'training_templates': False,
            'offers': False,
            'renewal_log': False,
            'supplements_water': False,
            'attendance_backup': False,
        })
        return perms

    # Default for any new / normal account → attendance only
    return {
        'attendance': True,
    }


def get_current_user():
    """Return current user dict with 'permissions' (dict) included."""
    user_id = session.get('user_id')
    if not user_id:
        return None

    user = query_db(
        'SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s',
        (user_id,),
        one=True,
    )
    if not user:
        return None

    # Super admin shortcut
    if user.get('username') == 'rino':
        user['permissions'] = {'super_admin': True}
        return user

    perms = _load_permissions(user.get('permissions'))
    user['permissions'] = perms
    return user


def login_required(f):
    """Basic authentication check (no specific permission)."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


def permission_required(permission_key):
    """
    Decorator for fine-grained authorization.
    - Rino (super admin) always allowed.
    - Unapproved users are blocked from everything except login/signup.
    """
    def decorator(f):
        @wraps(f)
        def wrapped(*args, **kwargs):
            if 'user_id' not in session:
                flash('You must log in first!', 'error')
                return redirect(url_for('login'))

            user = get_current_user()
            if not user:
                session.clear()
                flash('Session expired. Please log in again.', 'error')
                return redirect(url_for('login'))

            username = user.get('username')

            # Super admin bypass
            if username == 'rino':
                return f(*args, **kwargs)

            # Block unapproved users from everything except attendance (handled separately)
            if not user.get('is_approved'):
                flash('Your account is pending Rino approval.', 'error')
                return redirect(url_for('attendance_table'))

            perms = user.get('permissions') or {}
            if not perms.get(permission_key):
                flash('You do not have permission to access this page!', 'error')
                # For this app, unauthorized users are always redirected to attendance table
                return redirect(url_for('attendance_table'))

            return f(*args, **kwargs)
        return wrapped
    return decorator


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


# === Ahmed Adel Only Decorator ===
def ahmed_adel_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        if session.get('username') != 'ahmed_adel':
            flash('You do not have permission to access this page!', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# === Ayman Ashour Only Decorator ===
def ayman_ashour_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        if session.get('username') != 'ayman_ashour':
            flash('You do not have permission to access this page!', 'error')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function


# @app.teardown_appcontext
# def teardown_db(exception):
#     close_db()

# === Language Translation System ===
TRANSLATIONS = {
    'en': {
        'welcome': 'Welcome',
        'change_password': 'Change Password',
        'search_by_id': 'Search by ID',
        'search_by_name': 'Search by Name',
        'search_by_phone': 'Search by Phone',
        'add_new_member': 'Add New Member',
        'member_id': 'Member ID',
        'member_name': 'Member Name',
        'phone_number': 'Phone Number',
        'name': 'Name',
        'email': 'Email',
        'phone': 'Phone',
        'birthdate': 'Birthdate',
        'gender': 'Gender',
        'male': 'Male',
        'female': 'Female',
        'actual_starting_date': 'Actual Starting Date',
        'starting_date': 'Starting Date',
        'membership_package': 'Membership Package',
        'add_member': 'Add Member',
        'view_all_members': 'View All Members',
        'view_edit_logs': 'View Edit Logs',
        'renewal_log': 'Renewal Log',
        'all_invoices': 'All Invoices',
        'undo_actions': 'Undo Actions',
        'supplements_water': 'Supplements & Water',
        'online_users': 'Online Users',
        'attendance_table': 'Attendance Table',
        'attendance_backup': 'Attendance Backup',
        'invitations': 'Invitations',
        'offers': 'Offers',
        'data_management': 'Data Management',
        'logout': 'Logout',
        'enter_member_id': 'Enter Member ID',
        'enter_member_name': 'Enter Member Name',
        'enter_phone_number': 'Enter Phone Number',
        'full_name': 'Full Name',
        'email_address': 'Email Address',
        'select_package': 'Select Package',
        'search': 'Search',
        'rival_gym_system': 'Rival Gym System',
        'language': 'Language',
        'arabic': 'Arabic',
        'english': 'English',
        'login': 'Login',
        'signup': 'Sign Up',
        'username': 'Username',
        'password': 'Password',
        'old_password': 'Old Password',
        'new_password': 'New Password',
        'confirm_password': 'Confirm New Password',
        'back_to_home': 'Back to Home',
        'home': 'Home',
        'edit': 'Edit',
        'delete': 'Delete',
        'save': 'Save',
        'cancel': 'Cancel',
        'submit': 'Submit',
        'all_members': 'All Members',
        'edit_logs': 'Edit Logs',
        'edit_member': 'Edit Member',
        'delete_member': 'Delete Member',
        'freeze': 'Freeze',
        'use_freeze': 'Use Freeze',
        'freeze_used': 'Used',
        'status': 'Status',
        'valid': 'Valid',
        'expired': 'Expired',
        'age': 'Age',
        'end_date': 'End Date',
        'fees': 'Fees',
        'comment': 'Comment',
        'no_results': 'No results found',
        'loading': 'Loading...',
        'error': 'Error',
        'success': 'Success',
        'confirm': 'Confirm',
        'are_you_sure': 'Are you sure?',
        'this_action_cannot_be_undone': 'This action cannot be undone!',
        'send': 'Send',
        'send_message': 'Send Message',
        'message': 'Message',
        'enter_message': 'Enter your message here...',
        'back': 'Back',
        'next': 'Next',
        'previous': 'Previous',
        'first': 'First',
        'last': 'Last',
        'page': 'Page',
        'of': 'of',
        'total': 'total',
        'members': 'members',
        'download': 'Download',
        'download_csv': 'Download CSV',
        'create': 'Create',
        'update': 'Update',
        'close': 'Close',
        'yes': 'Yes',
        'no': 'No'
    },
    'ar': {
        'welcome': 'مرحباً',
        'change_password': 'تغيير كلمة المرور',
        'search_by_id': 'البحث بالرقم',
        'search_by_name': 'البحث بالاسم',
        'search_by_phone': 'البحث بالهاتف',
        'add_new_member': 'إضافة عضو جديد',
        'member_id': 'رقم العضو',
        'member_name': 'اسم العضو',
        'phone_number': 'رقم الهاتف',
        'name': 'الاسم',
        'email': 'البريد الإلكتروني',
        'phone': 'الهاتف',
        'birthdate': 'تاريخ الميلاد',
        'gender': 'الجنس',
        'male': 'ذكر',
        'female': 'أنثى',
        'actual_starting_date': 'تاريخ البدء الفعلي',
        'starting_date': 'تاريخ البدء',
        'membership_package': 'باقة العضوية',
        'add_member': 'إضافة عضو',
        'view_all_members': 'عرض جميع الأعضاء',
        'view_edit_logs': 'عرض سجلات التعديل',
        'renewal_log': 'سجل التجديد',
        'all_invoices': 'جميع الفواتير',
        'undo_actions': 'تراجع عن الإجراءات',
        'supplements_water': 'المكملات والماء',
        'online_users': 'المستخدمون المتصلون',
        'attendance_table': 'جدول الحضور',
        'attendance_backup': 'نسخة احتياطية للحضور',
        'invitations': 'الدعوات',
        'offers': 'العروض',
        'data_management': 'إدارة البيانات',
        'logout': 'تسجيل الخروج',
        'enter_member_id': 'أدخل رقم العضو',
        'enter_member_name': 'أدخل اسم العضو',
        'enter_phone_number': 'أدخل رقم الهاتف',
        'full_name': 'الاسم الكامل',
        'email_address': 'عنوان البريد الإلكتروني',
        'select_package': 'اختر الباقة',
        'search': 'بحث',
        'rival_gym_system': 'نظام ريڤال جيم',
        'language': 'اللغة',
        'arabic': 'العربية',
        'english': 'الإنجليزية',
        'login': 'تسجيل الدخول',
        'signup': 'إنشاء حساب',
        'username': 'اسم المستخدم',
        'password': 'كلمة المرور',
        'old_password': 'كلمة المرور القديمة',
        'new_password': 'كلمة المرور الجديدة',
        'confirm_password': 'تأكيد كلمة المرور الجديدة',
        'back_to_home': 'العودة للصفحة الرئيسية',
        'home': 'الرئيسية',
        'edit': 'تعديل',
        'delete': 'حذف',
        'save': 'حفظ',
        'cancel': 'إلغاء',
        'submit': 'إرسال',
        'all_members': 'جميع الأعضاء',
        'edit_logs': 'سجلات التعديل',
        'edit_member': 'تعديل العضو',
        'delete_member': 'حذف العضو',
        'freeze': 'تجميد',
        'use_freeze': 'استخدام التجميد',
        'freeze_used': 'مستخدم',
        'status': 'الحالة',
        'valid': 'نشط',
        'expired': 'منتهي',
        'age': 'العمر',
        'end_date': 'تاريخ الانتهاء',
        'fees': 'الرسوم',
        'comment': 'تعليق',
        'no_results': 'لا توجد نتائج',
        'loading': 'جاري التحميل...',
        'error': 'خطأ',
        'success': 'نجح',
        'confirm': 'تأكيد',
        'are_you_sure': 'هل أنت متأكد؟',
        'this_action_cannot_be_undone': 'لا يمكن التراجع عن هذا الإجراء!',
        'send': 'إرسال',
        'send_message': 'إرسال رسالة',
        'message': 'الرسالة',
        'enter_message': 'أدخل رسالتك هنا...',
        'back': 'رجوع',
        'next': 'التالي',
        'previous': 'السابق',
        'first': 'الأول',
        'last': 'الأخير',
        'page': 'صفحة',
        'of': 'من',
        'total': 'إجمالي',
        'members': 'أعضاء',
        'download': 'تحميل',
        'download_csv': 'تحميل CSV',
        'create': 'إنشاء',
        'update': 'تحديث',
        'close': 'إغلاق',
        'yes': 'نعم',
        'no': 'لا'
    }
}

def get_language():
    """Get current language from session, default to English"""
    return session.get('language', 'en')

def get_translation(key, language=None):
    """Get translation for a key"""
    if language is None:
        language = get_language()
    return TRANSLATIONS.get(language, TRANSLATIONS['en']).get(key, key)

@app.context_processor
def inject_translations():
    """Make translations available to all templates"""
    lang = get_language()
    return {
        't': TRANSLATIONS.get(lang, TRANSLATIONS['en']),
        'current_lang': lang,
        'is_rtl': lang == 'ar'
    }

@app.route('/toggle_language')
def toggle_language():
    """Toggle between English and Arabic - works for all pages including login"""
    current_lang = session.get('language', 'en')
    new_lang = 'ar' if current_lang == 'en' else 'en'
    session['language'] = new_lang
    session.permanent = True
    # Redirect back to the page they came from, or login if not logged in
    referrer = request.referrer
    if referrer:
        return redirect(referrer)
    # If no referrer, try to go to index if logged in, otherwise login
    if 'user_id' in session:
        return redirect(url_for('index'))
    else:
        return redirect(url_for('login'))

@app.route('/')
@app.route('/home')
@permission_required('index')
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

# Online users tracking (simple in-memory implementation)
_active_users = {}  # user_id -> {'username': str, 'last_activity': datetime, 'ip_address': str, 'login_time': datetime}
_ACTIVITY_TIMEOUT = timedelta(minutes=5)  # Consider user offline after 5 minutes of inactivity

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

def reset_all_login_attempts():
    """Reset all login attempt lockouts"""
    global _login_attempts
    _login_attempts.clear()
    return True

@app.route('/admin/reset_login_lockout', methods=['GET'])
@login_required
def reset_login_lockout():
    """Admin route to reset all login attempt lockouts"""
    reset_all_login_attempts()
    flash('All login attempt lockouts have been reset.', 'success')
    return redirect(url_for('index'))

@app.route('/reset_lockout', methods=['GET'])
@csrf.exempt
def reset_lockout_public():
    """Public route to reset login lockout (requires secret token)"""
    # Check for secret token in query parameter or environment variable
    secret_token = os.environ.get('RESET_LOCKOUT_TOKEN', 'reset_lockout_12345')
    provided_token = request.args.get('token', '')
    
    if provided_token == secret_token:
        reset_all_login_attempts()
        return jsonify({'success': True, 'message': 'All login attempt lockouts have been reset.'}), 200
    else:
        return jsonify({'success': False, 'message': 'Invalid token.'}), 403

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
                'SELECT id, username, password, email_verified, is_approved, permissions FROM users WHERE username = %s',
                (username,), one=True
            )
            # Fix: check_password_hash takes (hash, password) not (password, hash)
            if user and check_password_hash(user['password'], password):
                # Email verification is now optional (auto-verified on signup)
                # No need to check email_verified anymore

                # Block login if account not yet approved (except rino)
                if user.get('username') != 'rino' and not user.get('is_approved'):
                    flash('Your account is pending Rino approval.', 'error')
                    return render_template('login.html')

                # Initialize default permissions if none set yet
                raw_perms = user.get('permissions')
                if not raw_perms:
                    default_perms = get_default_permissions_for_username(user.get('username'))
                    try:
                        query_db(
                            'UPDATE users SET permissions = %s WHERE id = %s',
                            (Json(default_perms), user['id']),
                            commit=True
                        )
                        user['permissions'] = default_perms
                    except Exception as perm_error:
                        print(f\"Error initializing permissions for user {user.get('username')}: {perm_error}\")

                session['user_id'] = user['id']
                session['username'] = user['username']
                session.permanent = True  # Enable permanent session
                clear_login_attempts(ip_address)
                
                # Track user as online
                now = datetime.now()
                _active_users[user['id']] = {
                    'username': user['username'],
                    'login_time': now,
                    'last_activity': now,
                    'ip_address': ip_address
                }
                
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
    # Remove user from online tracking
    user_id = session.get('user_id')
    if user_id and user_id in _active_users:
        del _active_users[user_id]
    
    session.clear()
    flash('Logout successful', 'success')
    return redirect(url_for('login'))

@app.route('/online_users')
@rino_required
def online_users():
    """Show who is currently online and logged in (Rino only)"""
    try:
        online_users_list = get_online_users()
        current_time = datetime.now()
        return render_template('online_users.html', 
                             online_users=online_users_list,
                             current_time=current_time)
    except Exception as e:
        print(f"Error getting online users: {e}")
        import traceback
        traceback.print_exc()
        flash(f'Error loading online users: {str(e)}', 'error')
        return redirect(url_for('index'))

def update_all_membership_statuses():
    """Update all membership statuses in the database based on current end dates"""
    try:
        today = datetime.now().date()
        all_members = query_db('SELECT id, end_date, membership_status FROM members WHERE end_date IS NOT NULL AND end_date != %s', ('',))
        
        updated_count = 0
        for member in all_members:
            end_date_str = member.get('end_date', '').strip()
            if not end_date_str:
                continue
            
            # Parse end date
            try:
                # Try different date formats
                date_formats = [
                    '%Y-%m-%d',      # 2024-12-31
                    '%m/%d/%Y',       # 12/31/2024
                    '%d/%m/%Y',       # 31/12/2024
                    '%m-%d-%Y',       # 12-31-2024
                    '%d-%m-%Y',       # 31-12-2024
                    '%Y/%m/%d',       # 2024/12/31
                ]
                
                end_date_parsed = None
                for fmt in date_formats:
                    try:
                        end_date_parsed = datetime.strptime(end_date_str[:10], fmt).date()
                        break
                    except (ValueError, IndexError):
                        continue
                
                if end_date_parsed:
                    # Calculate correct status
                    new_status = "VAL" if end_date_parsed >= today else "EX"
                    old_status = member.get('membership_status', '')
                    
                    # Only update if status changed
                    if new_status != old_status:
                        query_db(
                            'UPDATE members SET membership_status = %s WHERE id = %s',
                            (new_status, member['id']),
                            commit=True
                        )
                        updated_count += 1
                        print(f"Updated member {member['id']}: {old_status} -> {new_status}")
            except Exception as e:
                print(f"Error updating status for member {member.get('id')}: {e}")
                continue
        
        return updated_count
    except Exception as e:
        print(f"Error in update_all_membership_statuses: {e}")
        import traceback
        traceback.print_exc()
        return 0

@app.route('/admin/update_all_statuses')
@rino_required
def update_all_statuses():
    """Update all membership statuses in database (Rino only)"""
    try:
        updated_count = update_all_membership_statuses()
        flash(f'Successfully updated {updated_count} membership status(es) in the database.', 'success')
    except Exception as e:
        print(f"Error updating statuses: {e}")
        flash(f'Error updating statuses: {str(e)}', 'error')
    return redirect(url_for('all_members'))

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
            # New accounts are created as not approved; Rino must approve them
            query_db(
                'INSERT INTO users (username, email, password, email_verified, verification_token, token_expires, is_approved) VALUES (%s, %s, %s, %s, %s, %s, %s)',
                (username, email, hashed_password, False, verification_token, token_expires, False), commit=True
            )
            
            # Auto-verify email (no email sending)
            query_db(
                'UPDATE users SET email_verified = TRUE WHERE id = (SELECT id FROM users WHERE username = %s ORDER BY id DESC LIMIT 1)',
                (username,), commit=True
            )
            
            flash('Account created successfully! Your account is pending Rino approval before you can log in.', 'success')
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
        
        # Create invoice for new member
        package_name = f"{numeric_value} {unit}".strip()
        create_invoice(
            member_id=added_id,
            member_name=member_name,
            invoice_type='new_member',
            package_name=package_name,
            amount=member_membership_fees,
            created_by=username,
            notes=f'New member registration - {package_name}'
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
    try:
        # Get individual column search queries
        search_id = request.args.get('search_id', '').strip()
        search_name = request.args.get('search_name', '').strip()
        search_email = request.args.get('search_email', '').strip()
        search_phone = request.args.get('search_phone', '').strip()
        search_age = request.args.get('search_age', '').strip()
        search_gender = request.args.get('search_gender', '').strip()
        search_actual_start = request.args.get('search_actual_start', '').strip()
        search_start_date = request.args.get('search_start_date', '').strip()
        search_end_date = request.args.get('search_end_date', '').strip()
        search_package = request.args.get('search_package', '').strip()
        search_fees = request.args.get('search_fees', '').strip()
        search_status = request.args.get('search_status', '').strip()
        search_invitations = request.args.get('search_invitations', '').strip()
        search_comment = request.args.get('search_comment', '').strip()
        
        # Pagination: 50 items per page
        page = request.args.get('page', 1, type=int)
        per_page = 50
        offset = (page - 1) * per_page
        
        # Build WHERE conditions for each column
        where_conditions = []
        params = []
        
        if search_id:
            where_conditions.append("CAST(id AS TEXT) ILIKE %s")
            params.append(f'%{search_id}%')
        
        if search_name:
            where_conditions.append("name ILIKE %s")
            params.append(f'%{search_name}%')
        
        if search_email:
            where_conditions.append("COALESCE(email, '') ILIKE %s")
            params.append(f'%{search_email}%')
        
        if search_phone:
            where_conditions.append("COALESCE(phone, '') ILIKE %s")
            params.append(f'%{search_phone}%')
        
        if search_age:
            where_conditions.append("CAST(age AS TEXT) ILIKE %s")
            params.append(f'%{search_age}%')
        
        if search_gender:
            where_conditions.append("COALESCE(gender, '') ILIKE %s")
            params.append(f'%{search_gender}%')
        
        if search_actual_start:
            where_conditions.append("COALESCE(actual_starting_date, '') ILIKE %s")
            params.append(f'%{search_actual_start}%')
        
        if search_start_date:
            where_conditions.append("COALESCE(starting_date, '') ILIKE %s")
            params.append(f'%{search_start_date}%')
        
        if search_end_date:
            where_conditions.append("COALESCE(end_date, '') ILIKE %s")
            params.append(f'%{search_end_date}%')
        
        if search_package:
            where_conditions.append("COALESCE(membership_packages, '') ILIKE %s")
            params.append(f'%{search_package}%')
        
        if search_fees:
            where_conditions.append("CAST(membership_fees AS TEXT) ILIKE %s")
            params.append(f'%{search_fees}%')
        
        if search_status:
            where_conditions.append("COALESCE(membership_status, '') ILIKE %s")
            params.append(f'%{search_status}%')
        
        if search_invitations:
            where_conditions.append("CAST(COALESCE(invitations, 0) AS TEXT) ILIKE %s")
            params.append(f'%{search_invitations}%')
        
        if search_comment:
            where_conditions.append("COALESCE(comment, '') ILIKE %s")
            params.append(f'%{search_comment}%')
        
        # Build query
        if where_conditions:
            where_clause = " AND ".join(where_conditions)
            base_query = f'SELECT * FROM members WHERE {where_clause} ORDER BY id ASC'
            count_query = f'SELECT COUNT(*) as count FROM members WHERE {where_clause}'
            
            # Get total count for pagination
            total_count = query_db(count_query, tuple(params), one=True)
            total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
            
            # Get paginated data with search
            members_data = query_db(
                base_query + ' LIMIT %s OFFSET %s',
                tuple(params) + (per_page, offset)
            )
        else:
            # No search - get all members
            total_count = query_db('SELECT COUNT(*) as count FROM members', one=True)
            total_pages = (total_count['count'] + per_page - 1) // per_page if total_count else 1
            
            members_data = query_db(
                'SELECT * FROM members ORDER BY id ASC LIMIT %s OFFSET %s',
                (per_page, offset)
            )
        
        # Process members to add is_expired flag for freeze button logic
        # Also recalculate status based on current date to ensure accuracy
        from datetime import datetime
        today = datetime.now().date()
        
        processed_members = []
        if members_data:
            for member in members_data:
                member_dict = dict(member) if hasattr(member, 'keys') else member
                is_expired = False
                
                # Check if end_date is expired and recalculate status
                end_date_str = member_dict.get('end_date')
                if end_date_str:
                    try:
                        # Try to parse various date formats
                        date_formats = [
                            '%Y-%m-%d',      # 2024-12-31
                            '%m/%d/%Y',       # 12/31/2024
                            '%d/%m/%Y',       # 31/12/2024
                            '%m-%d-%Y',       # 12-31-2024
                            '%d-%m-%Y',       # 31-12-2024
                            '%Y/%m/%d',       # 2024/12/31
                        ]
                        
                        end_date_parsed = None
                        for fmt in date_formats:
                            try:
                                end_date_parsed = datetime.strptime(str(end_date_str).strip()[:10], fmt).date()
                                break
                            except (ValueError, IndexError):
                                continue
                        
                        if end_date_parsed:
                            if end_date_parsed < today:
                                is_expired = True
                            # Recalculate status based on current date
                            # This ensures the displayed status is always accurate
                            recalculated_status = compare_dates(end_date_str)
                            if recalculated_status and recalculated_status != member_dict.get('membership_status'):
                                # Update the displayed status (but don't update DB unless explicitly requested)
                                member_dict['membership_status'] = recalculated_status
                                member_dict['status_updated'] = True  # Flag to show it was recalculated
                    except Exception as e:
                        print(f"Error parsing end_date for member {member_dict.get('id')}: {e}")
                
                member_dict['is_expired'] = is_expired
                processed_members.append(member_dict)
        
        return render_template("all_members.html", 
                            members_data=processed_members,
                            page=page,
                            total_pages=total_pages,
                            total_count=total_count['count'] if total_count else 0,
                            search_id=search_id,
                            search_name=search_name,
                            search_email=search_email,
                            search_phone=search_phone,
                            search_age=search_age,
                            search_gender=search_gender,
                            search_actual_start=search_actual_start,
                            search_start_date=search_start_date,
                            search_end_date=search_end_date,
                            search_package=search_package,
                            search_fees=search_fees,
                            search_status=search_status,
                            search_invitations=search_invitations,
                            search_comment=search_comment)
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
                
                # Check if member is reactivating (start_date or end_date changed to extend membership)
                # If freeze was used, reset it so they can use it again
                from datetime import datetime
                should_reset_freeze = False
                
                # Check if starting_date changed (reactivation)
                old_starting_date = old_member_dict.get('starting_date', '')
                if starting_date and old_starting_date:
                    try:
                        # Normalize dates for comparison
                        old_starting_normalized = format_date_for_input(old_starting_date)
                        new_starting_normalized = starting_date if starting_date else ''
                        
                        if new_starting_normalized and old_starting_normalized and new_starting_normalized != old_starting_normalized:
                            # Starting date changed - this is a reactivation
                            should_reset_freeze = True
                            
                            # Log the renewal
                            package_name = f"{numeric_value} {unit}".strip()
                            if package_name:
                                log_renewal(
                                    member_id=member_id,
                                    package_name=package_name,
                                    renewal_date=starting_date,
                                    fees=fees,
                                    edited_by=username
                                )
                                
                                # Create invoice for renewal
                                member = get_member(member_id)
                                if member:
                                    create_invoice(
                                        member_id=member_id,
                                        member_name=member.get('name', 'Unknown'),
                                        invoice_type='renewal',
                                        package_name=package_name,
                                        amount=fees,
                                        created_by=username,
                                        notes=f'Membership renewal - {package_name}'
                                    )
                    except Exception as e:
                        print(f"Error comparing starting dates: {e}")
                
                # Check if end_date changed to a future date (reactivation)
                old_end_date = old_member_dict.get('end_date', '')
                if end_date and old_end_date:
                    try:
                        # Try to parse dates
                        date_formats = [
                            '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y',
                            '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d'
                        ]
                        
                        old_end_parsed = None
                        new_end_parsed = None
                        
                        for fmt in date_formats:
                            try:
                                if old_end_date:
                                    old_end_parsed = datetime.strptime(str(old_end_date).strip()[:10], fmt).date()
                                if end_date:
                                    new_end_parsed = datetime.strptime(str(end_date).strip()[:10], fmt).date()
                                break
                            except (ValueError, IndexError):
                                continue
                        
                        # If new end_date is in the future and different from old, it's a reactivation
                        if new_end_parsed and old_end_parsed:
                            today = datetime.now().date()
                            if new_end_parsed > old_end_parsed and new_end_parsed > today:
                                should_reset_freeze = True
                        elif new_end_parsed:
                            # New end date exists and old didn't, check if it's in future
                            today = datetime.now().date()
                            if new_end_parsed > today:
                                should_reset_freeze = True
                    except Exception as e:
                        print(f"Error comparing end dates: {e}")
                
                # Prepare update parameters
                update_params = {
                    'name': name, 'email': email, 'phone': phone, 'age': age, 'gender': gender,
                    'birthdate': birthdate, 'actual_starting_date': actual_starting_date,
                    'starting_date': starting_date, 'end_date': end_date,
                    'membership_packages': f"{numeric_value} {unit}",
                    'membership_fees': fees, 'membership_status': status,
                    'invitations': invitations, 'comment': comment,
                    'edited_by': username
                }
                
                # Reset freeze_used if member is reactivating and had used freeze
                # Also recalculate invitations if reactivating (they're already calculated, but ensure they're updated)
                reset_messages = []
                if should_reset_freeze and old_member_dict.get('freeze_used'):
                    update_params['freeze_used'] = False
                    reset_messages.append("Freeze has been reset")
                
                # Check if invitations need to be recalculated (if package changed or reactivating)
                old_package = old_member_dict.get('membership_packages', '').strip()
                new_package = f"{numeric_value} {unit}".strip()
                old_invitations = old_member_dict.get('invitations', 0) or 0
                
                if should_reset_freeze and old_invitations != invitations:
                    # Invitations are already recalculated in update_params, but add message if changed
                    reset_messages.append("Invitations recalculated")
                
                update_member(member_id, **update_params)
                
                # Show appropriate success message
                if reset_messages:
                    flash(f"Member updated successfully! {', '.join(reset_messages)} due to membership reactivation.", "success")
                else:
                    flash("Member updated successfully!", "success")
                
                return redirect(url_for("index"))
            else:
                # Member not found, but try to update anyway
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
@permission_required('delete_member')
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
@permission_required('attendance')
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
            
            # Check if member's membership is expired
            from datetime import datetime
            today = datetime.now().date()
            end_date_str = member.get('end_date')
            is_expired = False
            
            if end_date_str:
                try:
                    date_formats = [
                        '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y',
                        '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d'
                    ]
                    
                    end_date_parsed = None
                    for fmt in date_formats:
                        try:
                            end_date_parsed = datetime.strptime(str(end_date_str).strip()[:10], fmt).date()
                            break
                        except (ValueError, IndexError):
                            continue
                    
                    if end_date_parsed and end_date_parsed < today:
                        is_expired = True
                except Exception as e:
                    print(f"Error parsing end_date for member {member_id}: {e}")
            
            # Check if expired or has no invitations
            if is_expired:
                flash(f'N/A - {member["name"]} (ID: {member_id}) doesn\'t have invitations. Membership expired.', 'error')
                return redirect(url_for('invitations'))
            
            current_invitations = member.get('invitations', 0) or 0
            if current_invitations <= 0:
                flash(f'{member["name"]} (ID: {member_id}) doesn\'t have invitations. Available invitations: 0', 'error')
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
        
        # Get all members with is_expired flag for JavaScript
        from datetime import datetime
        today = datetime.now().date()
        all_members = query_db('SELECT id, name, invitations, end_date FROM members ORDER BY id ASC') or []
        
        # Process members to add is_expired flag
        processed_members = []
        for member in all_members:
            member_dict = dict(member) if hasattr(member, 'keys') else member
            is_expired = False
            
            # Check if end_date is expired
            end_date_str = member_dict.get('end_date')
            if end_date_str:
                try:
                    # Try to parse various date formats
                    date_formats = [
                        '%Y-%m-%d', '%m/%d/%Y', '%d/%m/%Y',
                        '%m-%d-%Y', '%d-%m-%Y', '%Y/%m/%d'
                    ]
                    
                    end_date_parsed = None
                    for fmt in date_formats:
                        try:
                            end_date_parsed = datetime.strptime(str(end_date_str).strip()[:10], fmt).date()
                            break
                        except (ValueError, IndexError):
                            continue
                    
                    if end_date_parsed and end_date_parsed < today:
                        is_expired = True
                except Exception as e:
                    print(f"Error parsing end_date for member {member_dict.get('id')}: {e}")
            
            member_dict['is_expired'] = is_expired
            processed_members.append(member_dict)
        
        return render_template('invitations.html', 
                             invitations_data=invitations_data or [],
                             members_data=processed_members,
                             page=page,
                             total_pages=total_pages,
                             total_count=total_count['count'] if total_count else 0)
    except Exception as e:
        print(f"Error in invitations GET route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading invitations: {str(e)}", "error")
        return render_template('invitations.html', invitations_data=[], members_data=[], page=1, total_pages=1, total_count=0)

@app.route('/invoices')
@login_required
def invoices_list():
    """Display all invoices"""
    try:
        from urllib.parse import quote
        invoices = get_all_invoices() or []
        # Format WhatsApp messages for each invoice
        from flask import request as flask_request
        base_url = flask_request.host_url.rstrip('/')
        
        for invoice in invoices:
            if invoice.get('member_phone'):
                invoice_type_text = 'New Member Registration' if invoice.get('invoice_type') == 'new_member' else 'Membership Renewal'
                invoice_date_str = invoice.get('invoice_date')
                if invoice_date_str and not isinstance(invoice_date_str, str):
                    invoice_date_str = invoice_date_str.strftime('%Y-%m-%d')
                elif not invoice_date_str:
                    invoice_date_str = 'N/A'
                
                # Create permanent PDF download link (no login required, no token needed)
                # Simple permanent link using invoice number - can be opened anytime
                invoice_number = invoice.get('invoice_number', '')
                pdf_url = f"{base_url}/invoice/{invoice_number}/pdf"
                
                invoice_message = f"📄 *Invoice {invoice.get('invoice_number', 'N/A')}*\n\n"
                invoice_message += f"Member: {invoice.get('member_name', 'N/A')}\n"
                invoice_message += f"Type: {invoice_type_text}\n"
                invoice_message += f"Package: {invoice.get('package_name') or 'N/A'}\n"
                invoice_message += f"Amount: ${invoice.get('amount', 0):.2f}\n"
                invoice_message += f"Date: {invoice_date_str}\n\n"
                invoice_message += f"📎 Download PDF: {pdf_url}\n\n"
                invoice_message += "Thank you for your business!"
                
                # Clean and format phone number for WhatsApp (Egypt country code: +20)
                phone_raw = str(invoice.get('member_phone', '')).strip()
                phone_clean = phone_raw.replace(' ', '').replace('-', '').replace('(', '').replace(')', '')
                
                # Handle Egyptian phone numbers
                if phone_clean:
                    # If it starts with +20, it already has country code
                    if phone_clean.startswith('+20'):
                        phone_clean = phone_clean[1:]  # Remove + for WhatsApp URL
                    # If it starts with 0020, remove it and add 20
                    elif phone_clean.startswith('0020'):
                        phone_clean = '20' + phone_clean[4:]
                    # If it starts with 20 (without +), keep it
                    elif phone_clean.startswith('20') and len(phone_clean) >= 12:
                        pass  # Already has country code
                    # If it starts with 0 (Egyptian format), replace 0 with 20
                    elif phone_clean.startswith('0'):
                        phone_clean = '20' + phone_clean[1:]
                    # If it doesn't start with country code, assume it's Egyptian and add 20
                    elif len(phone_clean) == 10 or len(phone_clean) == 11:
                        phone_clean = '20' + phone_clean
                    # If it's a short number, try to add country code
                    elif len(phone_clean) < 10:
                        phone_clean = '20' + phone_clean
                
                invoice['whatsapp_url'] = f"https://wa.me/{phone_clean}?text={quote(invoice_message)}"
            else:
                invoice['whatsapp_url'] = None
        
        return render_template('invoices_list.html', invoices=invoices)
    except Exception as e:
        print(f"Error in invoices_list route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading invoices: {str(e)}", "error")
        return render_template('invoices_list.html', invoices=[])

@app.route('/invoice/<int:invoice_id>')
@login_required
def view_invoice(invoice_id):
    """Display a single invoice"""
    try:
        invoice = get_invoice(invoice_id)
        if not invoice:
            flash("Invoice not found!", "error")
            return redirect(url_for('invoices_list'))
        
        # Get member details if member_id exists
        member = None
        if invoice.get('member_id'):
            member = get_member(invoice['member_id'])
        
        return render_template('invoice.html', invoice=invoice, member=member)
    except Exception as e:
        print(f"Error in view_invoice route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading invoice: {str(e)}", "error")
        return redirect(url_for('invoices_list'))

def generate_invoice_pdf_response(invoice):
    """Helper function to generate invoice PDF response - optimized for single page"""
    from reportlab.lib.pagesizes import letter
    from reportlab.lib import colors
    from reportlab.lib.units import inch
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from io import BytesIO
    from flask import Response
    
    # Get member details if member_id exists
    member = None
    if invoice.get('member_id'):
        member = get_member(invoice['member_id'])
    
    # Create PDF buffer
    buffer = BytesIO()
    
    # Custom colors matching the new design
    primary_color = colors.HexColor('#00d4ff')
    dark_bg = colors.HexColor('#1a1a2e')
    text_color = colors.HexColor('#1a1a1a')
    light_text = colors.HexColor('#6c757d')
    
    # Create document with minimal margins for single page
    doc = SimpleDocTemplate(buffer, pagesize=letter,
                            rightMargin=40, leftMargin=40,
                            topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    
    # Compact custom styles
    company_title_style = ParagraphStyle(
        'CompanyTitle',
        parent=styles['Heading1'],
        fontSize=32,
        textColor=primary_color,
        spaceAfter=4,
        fontName='Helvetica-Bold',
        leading=36,
    )
    
    tagline_style = ParagraphStyle(
        'Tagline',
        parent=styles['Normal'],
        fontSize=9,
        textColor=light_text,
        spaceAfter=8,
        fontName='Helvetica',
        leading=11,
    )
    
    invoice_badge_title_style = ParagraphStyle(
        'InvoiceBadgeTitle',
        parent=styles['Normal'],
        fontSize=8,
        textColor=primary_color,
        spaceAfter=6,
        fontName='Helvetica-Bold',
        leading=10,
    )
    
    invoice_number_style = ParagraphStyle(
        'InvoiceNumber',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=primary_color,
        spaceAfter=8,
        fontName='Helvetica-Bold',
        leading=28,
    )
    
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Normal'],
        fontSize=10,
        textColor=text_color,
        spaceAfter=8,
        fontName='Helvetica-Bold',
        leading=12,
    )
    
    # Compact header - side by side layout
    invoice_date_str = invoice['invoice_date'].strftime('%B %d, %Y') if hasattr(invoice['invoice_date'], 'strftime') else str(invoice['invoice_date'])
    invoice_type_str = 'New Member Registration' if invoice['invoice_type'] == 'new_member' else 'Membership Renewal'
    
    header_data = [
        [
            Paragraph("RIVAL GYM", company_title_style),
            Paragraph("INVOICE", invoice_badge_title_style)
        ],
        [
            Paragraph("Membership Management System", tagline_style),
            Paragraph(f"#{invoice['invoice_number']}", invoice_number_style)
        ],
        [
            Paragraph("Email: Rival.gym1@gmail.com<br/>Phone: +20 1003527758", tagline_style),
            Paragraph(f"Date: {invoice_date_str}<br/>Type: {invoice_type_str}", tagline_style)
        ]
    ]
    
    header_table = Table(header_data, colWidths=[4.2*inch, 2.3*inch])
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BACKGROUND', (1, 0), (1, -1), dark_bg),
        ('TEXTCOLOR', (1, 0), (1, 0), primary_color),
        ('TEXTCOLOR', (1, 1), (1, 1), primary_color),
        ('TEXTCOLOR', (1, 2), (1, 2), colors.white),
        ('LEFTPADDING', (1, 0), (1, -1), 15),
        ('RIGHTPADDING', (1, 0), (1, -1), 15),
        ('TOPPADDING', (1, 0), (1, -1), 12),
        ('BOTTOMPADDING', (1, 0), (1, -1), 12),
        ('TOPPADDING', (0, 0), (0, -1), 0),
        ('BOTTOMPADDING', (0, 0), (0, -1), 0),
    ]))
    elements.append(header_table)
    elements.append(Spacer(1, 0.2*inch))
    
    # Bill To and Invoice Details side by side
    bill_to_data = [
        ['Member Name:', invoice['member_name']],
        ['Member ID:', f"#{invoice['member_id']}" if invoice['member_id'] else 'N/A'],
    ]
    if member:
        if member.get('email'):
            bill_to_data.append(['Email:', member['email']])
        if member.get('phone'):
            bill_to_data.append(['Phone:', member['phone']])
    
    bill_to_table = Table(bill_to_data, colWidths=[1.2*inch, 2.8*inch])
    bill_to_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('TEXTCOLOR', (0, 0), (0, -1), light_text),
        ('TEXTCOLOR', (1, 0), (1, -1), text_color),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
    ]))
    
    items_data = [
        ['Description', 'Package', 'Amount'],
        [
            invoice_type_str,
            invoice['package_name'] or 'N/A',
            f"${float(invoice['amount']):.2f}" if invoice.get('amount') else '$0.00'
        ]
    ]
    
    items_table = Table(items_data, colWidths=[2.5*inch, 1.8*inch, 1.2*inch])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), dark_bg),
        ('TEXTCOLOR', (0, 0), (-1, 0), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME', (0, 1), (-1, 1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('FONTSIZE', (0, 1), (-1, 1), 9),
        ('FONTSIZE', (2, 1), (2, 1), 10),
        ('TEXTCOLOR', (2, 1), (2, 1), primary_color),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e9ecef')),
    ]))
    
    # Side by side layout
    side_by_side_data = [
        [Paragraph("<b>BILL TO</b>", section_title_style), Paragraph("<b>INVOICE DETAILS</b>", section_title_style)],
        [bill_to_table, items_table]
    ]
    
    side_by_side_table = Table(side_by_side_data, colWidths=[3.2*inch, 3.3*inch])
    side_by_side_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BOTTOMPADDING', (0, 1), (-1, 1), 0),
    ]))
    elements.append(side_by_side_table)
    elements.append(Spacer(1, 0.25*inch))
    
    # Total section - compact
    invoice_amount = float(invoice['amount']) if invoice['amount'] else 0.0
    total_data = [
        ['Subtotal:', f"${invoice_amount:.2f}"],
        ['Tax:', '$0.00'],
        ['Total Amount:', f"${invoice_amount:.2f}"],
    ]
    
    total_table = Table(total_data, colWidths=[4.5*inch, 2*inch])
    total_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), dark_bg),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#adb5bd')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.white),
        ('TEXTCOLOR', (0, 2), (0, 2), primary_color),
        ('TEXTCOLOR', (1, 2), (1, 2), primary_color),
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (0, 1), 10),
        ('FONTSIZE', (1, 0), (1, 1), 11),
        ('FONTSIZE', (0, 2), (0, 2), 11),
        ('FONTSIZE', (1, 2), (1, 2), 18),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 0), (-1, -1), 10),
        ('TOPPADDING', (0, 2), (-1, 2), 12),
        ('LEFTPADDING', (0, 0), (-1, -1), 15),
        ('RIGHTPADDING', (0, 0), (-1, -1), 15),
        ('LINEABOVE', (0, 2), (-1, 2), 2, primary_color),
    ]))
    elements.append(total_table)
    
    # Compact footer
    elements.append(Spacer(1, 0.3*inch))
    footer_style = ParagraphStyle(
        'Footer',
        parent=styles['Normal'],
        fontSize=9,
        textColor=light_text,
        spaceAfter=4,
        alignment=1,  # Center
        fontName='Helvetica',
    )
    
    thank_you_style = ParagraphStyle(
        'ThankYou',
        parent=styles['Normal'],
        fontSize=11,
        textColor=primary_color,
        spaceAfter=6,
        alignment=1,
        fontName='Helvetica-Bold',
    )
    
    elements.append(Paragraph("THANK YOU FOR YOUR BUSINESS!", thank_you_style))
    elements.append(Paragraph("This is a computer-generated invoice. No signature required.", footer_style))
    if invoice.get('created_by'):
        elements.append(Paragraph(f"Created by: {invoice['created_by']}", footer_style))
    
    from datetime import datetime
    current_year = datetime.now().year
    elements.append(Paragraph(f"© {current_year} Rival Gym. All rights reserved.", footer_style))
    
    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    
    # Create response
    response = Response(buffer.read(), mimetype='application/pdf')
    response.headers['Content-Disposition'] = f'attachment; filename=invoice_{invoice["invoice_number"]}.pdf'
    return response

@app.route('/invoice/<int:invoice_id>/pdf/public/<token>')
def download_invoice_pdf_public(invoice_id, token):
    """Public PDF download route (no login required) - uses token for basic security"""
    try:
        invoice = get_invoice(invoice_id)
        if not invoice:
            return "Invoice not found", 404
        
        # Verify token
        import hashlib
        invoice_number = invoice.get('invoice_number', '')
        expected_token = hashlib.md5(f"{invoice_number}{secret_key}".encode()).hexdigest()[:12]
        if token != expected_token:
            return "Invalid access token", 403
        
        # Generate and return PDF
        return generate_invoice_pdf_response(invoice)
    except Exception as e:
        print(f"Error generating public PDF: {e}")
        import traceback
        traceback.print_exc()
        return f"Error generating PDF: {str(e)}", 500

@app.route('/invoice/<path:invoice_number>/pdf')
def download_invoice_pdf_by_number(invoice_number):
    """Permanent PDF link using invoice number - can be opened anytime, no token needed
    This link is permanent and can be shared - it will always work to download the PDF.
    Format: /invoice/INV-2024-0001/pdf
    """
    try:
        # Find invoice by invoice number
        invoice = query_db(
            'SELECT * FROM invoices WHERE invoice_number = %s',
            (invoice_number,),
            one=True
        )
        
        if not invoice:
            return "Invoice not found", 404
        
        # Generate and return PDF directly
        return generate_invoice_pdf_response(invoice)
    except Exception as e:
        print(f"Error generating PDF by invoice number: {e}")
        import traceback
        traceback.print_exc()
        return f"Error generating PDF: {str(e)}", 500

@app.route('/invoice/<int:invoice_id>/pdf')
@login_required
def download_invoice_pdf(invoice_id):
    """Download invoice as PDF using reportlab (requires login)"""
    try:
        
        invoice = get_invoice(invoice_id)
        if not invoice:
            flash("Invoice not found!", "error")
            return redirect(url_for('invoices_list'))
        
        return generate_invoice_pdf_response(invoice)
    except Exception as e:
        print(f"Error generating PDF: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error generating PDF: {str(e)}", "error")
        return redirect(url_for('view_invoice', invoice_id=invoice_id))

@app.route('/renewal_log')
@permission_required('renewal_log')
def renewal_log():
    """Display renewal log with daily and monthly totals"""
    try:
        from datetime import datetime
        
        # Get all renewal logs
        renewal_logs = get_renewal_logs() or []
        
        # Get daily totals
        daily_totals = get_daily_totals() or []
        
        # Get current month total
        now = datetime.now()
        monthly_total = get_monthly_total(now.year, now.month)
        
        # Calculate total membership (all time)
        total_membership = 0.0
        if renewal_logs:
            for log in renewal_logs:
                fees = log.get('fees')
                if fees is not None:
                    try:
                        total_membership += float(fees)
                    except (ValueError, TypeError):
                        pass
        
        return render_template('renewal_log.html',
                             renewal_logs=renewal_logs,
                             daily_totals=daily_totals,
                             monthly_total=monthly_total,
                             total_membership=total_membership)
    except Exception as e:
        print(f"Error in renewal_log route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading renewal log: {str(e)}", "error")
        return render_template('renewal_log.html',
                             renewal_logs=[],
                             daily_totals=[],
                             monthly_total=0,
                             total_membership=0)

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
@permission_required('offers')
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
@permission_required('supplements_water')
def supplements():
    """Supplement and Water Management System"""
    try:
        # Ensure tables exist
        try:
            create_table()
        except Exception as table_error:
            print(f"Warning: Could not create/verify tables: {table_error}")
        
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
        # Return minimal safe defaults
        safe_stats = {
            'total_products': 0,
            'today_sales': 0,
            'cash_sales_today': 0,
            'visa_sales_today': 0,
            'month_sales': 0,
            'total_sales': 0,
            'total_sales_count': 0,
            'inventory_value': 0,
            'low_stock': 0,
            'top_products': [],
            'product_stats': [],
            'user_sales': [],
            'user_sales_today': []
        }
        return render_template('supplements.html', supplements=[], stats=safe_stats, recent_sales=[], is_rino=False)


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


@app.route('/staff_management')
@login_required
def staff_management():
    """Staff Management System"""
    try:
        # Ensure tables exist
        try:
            create_table()
        except Exception as table_error:
            print(f"Warning: Could not create/verify tables: {table_error}")
        
        staff_data = get_all_staff()
        staff_stats = get_staff_statistics()
        recent_purchases = get_staff_purchases(limit=50)
        supplements_data = get_all_supplements()
        is_rino = session.get('username') == 'rino'
        return render_template('staff_management.html', 
                             staff=staff_data or [],
                             stats=staff_stats,
                             recent_purchases=recent_purchases or [],
                             supplements=supplements_data or [],
                             is_rino=is_rino)
    except Exception as e:
        print(f"Error in staff_management route: {e}")
        import traceback
        traceback.print_exc()
        flash(f"Error loading staff management: {str(e)}", "error")
        # Return minimal safe defaults
        safe_stats = {
            'total_staff': 0,
            'total_staff_purchases': 0,
            'total_staff_purchase_count': 0,
            'total_staff_purchase_quantity': 0,
            'month_staff_purchases': 0,
            'staff_by_role': [],
            'staff_purchase_stats': []
        }
        return render_template('staff_management.html', staff=[], stats=safe_stats, recent_purchases=[], supplements=[], is_rino=False)


@app.route('/add_staff', methods=['POST'])
@rino_required
def add_staff_route():
    """Add a new staff member"""
    try:
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        hire_date = request.form.get('hire_date', '').strip() or None
        status = request.form.get('status', 'active').strip()
        notes = request.form.get('notes', '').strip() or None
        
        if not name or not role:
            flash('Name and role are required!', 'error')
            return redirect(url_for('staff_management'))
        
        add_staff(name, role, phone, email, hire_date, status, notes)
        flash(f'Staff member "{name}" added successfully!', 'success')
    except Exception as e:
        print(f"Error adding staff: {e}")
        flash(f'Error adding staff: {str(e)}', 'error')
    return redirect(url_for('staff_management'))


@app.route('/edit_staff/<int:staff_id>', methods=['POST'])
@rino_required
def edit_staff_route(staff_id):
    """Edit a staff member"""
    try:
        name = request.form.get('name', '').strip()
        role = request.form.get('role', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        hire_date = request.form.get('hire_date', '').strip() or None
        status = request.form.get('status', 'active').strip()
        notes = request.form.get('notes', '').strip() or None
        
        if not name or not role:
            flash('Name and role are required!', 'error')
            return redirect(url_for('staff_management'))
        
        update_staff(staff_id, name=name, role=role, phone=phone, email=email, hire_date=hire_date, status=status, notes=notes)
        flash(f'Staff member "{name}" updated successfully!', 'success')
    except Exception as e:
        print(f"Error editing staff: {e}")
        flash(f'Error updating staff: {str(e)}', 'error')
    return redirect(url_for('staff_management'))


@app.route('/delete_staff/<int:staff_id>', methods=['POST'])
@rino_required
def delete_staff_route(staff_id):
    """Delete a staff member"""
    try:
        staff_member = get_staff(staff_id)
        if staff_member:
            delete_staff(staff_id)
            flash(f'Staff member "{staff_member["name"]}" deleted successfully!', 'success')
        else:
            flash('Staff member not found!', 'error')
    except Exception as e:
        print(f"Error deleting staff: {e}")
        flash(f'Error deleting staff: {str(e)}', 'error')
    return redirect(url_for('staff_management'))


@app.route('/add_staff_purchase/<int:staff_id>', methods=['POST'])
@login_required
def add_staff_purchase_route(staff_id):
    """Record a staff purchase"""
    try:
        staff_member = get_staff(staff_id)
        if not staff_member:
            flash('Staff member not found!', 'error')
            return redirect(url_for('staff_management'))
        
        supplement_id = request.form.get('supplement_id', '').strip()
        if supplement_id:
            supplement_id = int(supplement_id)
            supplement = get_supplement(supplement_id)
            if not supplement:
                flash('Product not found!', 'error')
                return redirect(url_for('staff_management'))
            supplement_name = supplement['name']
            unit_price = supplement['price']
            
            if supplement['stock_quantity'] < int(request.form.get('quantity', 1)):
                flash(f'Insufficient stock! Available: {supplement["stock_quantity"]}', 'error')
                return redirect(url_for('staff_management'))
        else:
            supplement_name = request.form.get('supplement_name', '').strip()
            unit_price = float(request.form.get('unit_price', 0) or 0)
            supplement_id = None
        
        quantity = int(request.form.get('quantity', 1) or 1)
        total_price = unit_price * quantity
        notes = request.form.get('notes', '').strip() or None
        recorded_by = session.get('username', 'Unknown')
        
        if quantity <= 0:
            flash('Quantity must be greater than 0!', 'error')
            return redirect(url_for('staff_management'))
        
        add_staff_purchase(staff_id, staff_member['name'], supplement_id, supplement_name, quantity, unit_price, total_price, notes, recorded_by)
        flash(f'Purchase recorded: {quantity} x {supplement_name} = ${total_price:.2f} for {staff_member["name"]}', 'success')
    except Exception as e:
        print(f"Error recording staff purchase: {e}")
        flash(f'Error recording purchase: {str(e)}', 'error')
    return redirect(url_for('staff_management'))


# ========================================
# TRAINING TEMPLATES SYSTEM (نظام خطط تدريب جاهزة)
# ========================================

@app.route('/training_templates')
@permission_required('training_templates')
def training_templates():
    """Display all training templates"""
    try:
        templates = query_db(
            'SELECT * FROM training_templates ORDER BY created_at DESC',
            one=False
        ) or []
        
        # Process exercises JSON for each template
        for template in templates:
            if template.get('exercises'):
                if isinstance(template['exercises'], str):
                    try:
                        template['exercises'] = json.loads(template['exercises'])
                    except:
                        template['exercises'] = []
                elif not isinstance(template['exercises'], list):
                    template['exercises'] = []
            else:
                template['exercises'] = []
        
        return render_template('training_templates.html', templates=templates)
    except Exception as e:
        print(f"Error loading training templates: {e}")
        flash(f"Error loading templates: {str(e)}", "error")
        return render_template('training_templates.html', templates=[])

@app.route('/training_templates/create', methods=['GET', 'POST'])
@login_required
def create_training_template():
    """Create a new training template"""
    if request.method == 'POST':
        try:
            template_name = request.form.get('template_name', '').strip()
            category = request.form.get('category', '').strip()
            description = request.form.get('description', '').strip()
            exercises_json = request.form.get('exercises', '').strip()
            created_by = session.get('username', 'Unknown')
            
            if not template_name or not category or not exercises_json:
                flash('Template name, category, and exercises are required!', 'error')
                return render_template('create_training_template.html')
            
            # Validate JSON format
            try:
                exercises_data = json.loads(exercises_json)
                if not isinstance(exercises_data, list) or len(exercises_data) == 0:
                    flash('Please add at least one exercise!', 'error')
                    return render_template('create_training_template.html')
            except json.JSONDecodeError:
                flash('Invalid exercises data format!', 'error')
                return render_template('create_training_template.html')
            
            result = query_db(
                '''INSERT INTO training_templates 
                   (template_name, category, description, exercises, created_by)
                   VALUES (%s, %s, %s, %s, %s)
                   RETURNING id''',
                (template_name, category, description, Json(exercises_data), created_by),
                one=True,
                commit=True
            )
            
            flash(f'Training template "{template_name}" created successfully!', 'success')
            return redirect(url_for('training_templates'))
        except Exception as e:
            print(f"Error creating training template: {e}")
            flash(f"Error creating template: {str(e)}", "error")
    
    return render_template('create_training_template.html')

@app.route('/training_templates/<int:template_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_training_template(template_id):
    """Edit a training template"""
    template = query_db(
        'SELECT * FROM training_templates WHERE id = %s',
        (template_id,),
        one=True
    )
    
    if not template:
        flash('Template not found!', 'error')
        return redirect(url_for('training_templates'))
    
    if request.method == 'POST':
        try:
            template_name = request.form.get('template_name', '').strip()
            category = request.form.get('category', '').strip()
            description = request.form.get('description', '').strip()
            exercises_json = request.form.get('exercises', '').strip()
            
            if not template_name or not category:
                flash('Template name and category are required!', 'error')
                # Re-process exercises before rendering
                if template.get('exercises'):
                    if isinstance(template['exercises'], str):
                        try:
                            template['exercises'] = json.loads(template['exercises'])
                        except:
                            template['exercises'] = []
                    elif not isinstance(template['exercises'], list):
                        template['exercises'] = []
                else:
                    template['exercises'] = []
                return render_template('edit_training_template.html', template=template)
            
            if not exercises_json:
                flash('Please add at least one exercise!', 'error')
                # Re-process exercises before rendering
                if template.get('exercises'):
                    if isinstance(template['exercises'], str):
                        try:
                            template['exercises'] = json.loads(template['exercises'])
                        except:
                            template['exercises'] = []
                    elif not isinstance(template['exercises'], list):
                        template['exercises'] = []
                else:
                    template['exercises'] = []
                return render_template('edit_training_template.html', template=template)
            
            # Validate JSON format
            try:
                exercises_data = json.loads(exercises_json)
                if not isinstance(exercises_data, list) or len(exercises_data) == 0:
                    flash('Please add at least one exercise!', 'error')
                    return render_template('edit_training_template.html', template=template)
            except json.JSONDecodeError:
                flash('Invalid exercises data format!', 'error')
                # Re-process exercises before rendering
                if template.get('exercises'):
                    if isinstance(template['exercises'], str):
                        try:
                            template['exercises'] = json.loads(template['exercises'])
                        except:
                            template['exercises'] = []
                    elif not isinstance(template['exercises'], list):
                        template['exercises'] = []
                else:
                    template['exercises'] = []
                return render_template('edit_training_template.html', template=template)
            
            query_db(
                '''UPDATE training_templates 
                   SET template_name = %s, category = %s, description = %s, 
                       exercises = %s, updated_at = CURRENT_TIMESTAMP
                   WHERE id = %s''',
                (template_name, category, description, Json(exercises_data), template_id),
                commit=True
            )
            
            flash(f'Training template "{template_name}" updated successfully!', 'success')
            return redirect(url_for('training_templates'))
        except Exception as e:
            print(f"Error updating training template: {e}")
            flash(f"Error updating template: {str(e)}", "error")
    
    # Process exercises JSON before rendering template
    if template.get('exercises'):
        if isinstance(template['exercises'], str):
            try:
                template['exercises'] = json.loads(template['exercises'])
            except:
                template['exercises'] = []
        elif not isinstance(template['exercises'], list):
            template['exercises'] = []
    else:
        template['exercises'] = []
    
    return render_template('edit_training_template.html', template=template)

@app.route('/training_templates/<int:template_id>/delete', methods=['POST'])
@login_required
def delete_training_template(template_id):
    """Delete a training template"""
    try:
        template = query_db(
            'SELECT template_name FROM training_templates WHERE id = %s',
            (template_id,),
            one=True
        )
        
        if not template:
            flash('Template not found!', 'error')
            return redirect(url_for('training_templates'))
        
        query_db(
            'DELETE FROM training_templates WHERE id = %s',
            (template_id,),
            commit=True
        )
        
        flash(f'Training template "{template["template_name"]}" deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting training template: {e}")
        flash(f"Error deleting template: {str(e)}", "error")
    
    return redirect(url_for('training_templates'))

@app.route('/training_templates/<int:template_id>/assign', methods=['GET', 'POST'])
@login_required
def assign_training_template(template_id):
    """Assign a training template to a member"""
    template = query_db(
        'SELECT * FROM training_templates WHERE id = %s',
        (template_id,),
        one=True
    )
    
    if not template:
        flash('Template not found!', 'error')
        return redirect(url_for('training_templates'))
    
    if request.method == 'POST':
        try:
            member_id = request.form.get('member_id')
            plan_name = request.form.get('plan_name', '').strip() or template['template_name']
            exercises_json = request.form.get('exercises', '').strip()
            start_date = request.form.get('start_date', '')
            end_date = request.form.get('end_date', '')
            assigned_by = session.get('username', 'Unknown')
            
            if not member_id:
                flash('Please select a member!', 'error')
                members = query_db('SELECT id, name FROM members ORDER BY name', one=False) or []
                return render_template('assign_training_template.html', template=template, members=members)
            
            # Use provided exercises or template exercises
            if exercises_json:
                try:
                    exercises_data = json.loads(exercises_json)
                except:
                    exercises_data = template.get('exercises', [])
            else:
                exercises_data = template.get('exercises', [])
            
            query_db(
                '''INSERT INTO member_training_plans 
                   (member_id, template_id, plan_name, exercises, start_date, end_date, assigned_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)''',
                (member_id, template_id, plan_name, Json(exercises_data), start_date or None, end_date or None, assigned_by),
                commit=True
            )
            
            member = query_db('SELECT name FROM members WHERE id = %s', (member_id,), one=True)
            flash(f'Training plan assigned to {member["name"] if member else "member"} successfully!', 'success')
            return redirect(url_for('member_training_plans', member_id=member_id))
        except Exception as e:
            print(f"Error assigning training template: {e}")
            flash(f"Error assigning template: {str(e)}", "error")
    
    members = query_db('SELECT id, name FROM members ORDER BY name', one=False) or []
    return render_template('assign_training_template.html', template=template, members=members)

@app.route('/training_templates/<int:template_id>/plans')
@login_required
def view_template_plans(template_id):
    """View all plans that use this template"""
    try:
        template = query_db(
            'SELECT * FROM training_templates WHERE id = %s',
            (template_id,),
            one=True
        )
        
        if not template:
            flash('Template not found!', 'error')
            return redirect(url_for('training_templates'))
        
        # Process exercises JSON
        if template.get('exercises'):
            if isinstance(template['exercises'], str):
                try:
                    template['exercises'] = json.loads(template['exercises'])
                except:
                    template['exercises'] = []
            elif not isinstance(template['exercises'], list):
                template['exercises'] = []
        else:
            template['exercises'] = []
        
        # Get all plans using this template
        plans = query_db(
            '''SELECT mtp.*, m.name as member_name, m.id as member_id, m.phone as member_phone
               FROM member_training_plans mtp
               JOIN members m ON mtp.member_id = m.id
               WHERE mtp.template_id = %s
               ORDER BY mtp.created_at DESC''',
            (template_id,),
            one=False
        ) or []
        
        # Process exercises JSON for each plan
        for plan in plans:
            if plan.get('exercises'):
                if isinstance(plan['exercises'], str):
                    try:
                        plan['exercises'] = json.loads(plan['exercises'])
                    except:
                        plan['exercises'] = []
                elif not isinstance(plan['exercises'], list):
                    plan['exercises'] = []
        
        return render_template('template_plans.html', template=template, plans=plans)
    except Exception as e:
        print(f"Error loading template plans: {e}")
        flash(f"Error loading plans: {str(e)}", "error")
        return redirect(url_for('training_templates'))

@app.route('/member_training_plans/<int:member_id>')
@login_required
def member_training_plans(member_id):
    """View training plans for a specific member"""
    try:
        member = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
        if not member:
            flash('Member not found!', 'error')
            return redirect(url_for('all_members'))
        
        plans = query_db(
            '''SELECT mtp.*, tt.template_name, tt.category 
               FROM member_training_plans mtp
               LEFT JOIN training_templates tt ON mtp.template_id = tt.id
               WHERE mtp.member_id = %s
               ORDER BY mtp.created_at DESC''',
            (member_id,),
            one=False
        ) or []
        
        return render_template('member_training_plans.html', member=member, plans=plans)
    except Exception as e:
        print(f"Error loading member training plans: {e}")
        flash(f"Error loading plans: {str(e)}", "error")
        return redirect(url_for('all_members'))

@app.route('/training_plan/<int:plan_id>/view')
@login_required
def view_training_plan(plan_id):
    """View a single training plan in a formatted sheet"""
    try:
        plan = query_db(
            '''SELECT mtp.*, m.name as member_name, m.id as member_id, m.phone as member_phone, 
                      m.age as member_age, m.gender as member_gender,
                      tt.template_name, tt.category
               FROM member_training_plans mtp
               JOIN members m ON mtp.member_id = m.id
               LEFT JOIN training_templates tt ON mtp.template_id = tt.id
               WHERE mtp.id = %s''',
            (plan_id,),
            one=True
        )
        
        if not plan:
            flash('Training plan not found!', 'error')
            return redirect(url_for('all_members'))
        
        # Process exercises JSON
        if plan.get('exercises'):
            if isinstance(plan['exercises'], str):
                try:
                    plan['exercises'] = json.loads(plan['exercises'])
                except:
                    plan['exercises'] = []
            elif not isinstance(plan['exercises'], list):
                plan['exercises'] = []
        else:
            plan['exercises'] = []
        
        return render_template('view_training_plan_sheet.html', plan=plan)
    except Exception as e:
        print(f"Error loading training plan: {e}")
        flash(f"Error loading plan: {str(e)}", "error")
        return redirect(url_for('all_members'))

# ========================================
# PROGRESS TRACKING SYSTEM (نظام متابعة التقدم)
# ========================================

@app.route('/progress_tracking/<int:member_id>')
@login_required
def progress_tracking(member_id):
    """View progress tracking for a member with graphs"""
    try:
        member = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
        if not member:
            flash('Member not found!', 'error')
            return redirect(url_for('all_members'))
        
        # Get all progress entries
        progress_data = query_db(
            '''SELECT * FROM progress_tracking 
               WHERE member_id = %s 
               ORDER BY tracking_date DESC''',
            (member_id,),
            one=False
        ) or []
        
        # Prepare data for graphs - handle None values properly
        dates = [str(p['tracking_date']) for p in reversed(progress_data) if p.get('tracking_date')]
        weights = [float(p['weight']) for p in reversed(progress_data) if p.get('weight') is not None]
        body_fat = [float(p['body_fat']) for p in reversed(progress_data) if p.get('body_fat') is not None]
        muscle_mass = [float(p['muscle_mass']) for p in reversed(progress_data) if p.get('muscle_mass') is not None]
        
        # Process measurements and photos - handle JSON strings and arrays
        for p in progress_data:
            # Handle measurements JSON
            if p.get('measurements') and isinstance(p['measurements'], str):
                try:
                    p['measurements'] = json.loads(p['measurements'])
                except:
                    p['measurements'] = None
            
            # Handle photos array - PostgreSQL returns arrays as lists
            if p.get('photos'):
                if isinstance(p['photos'], str):
                    # Try to parse as JSON array or comma-separated
                    try:
                        p['photos'] = json.loads(p['photos'])
                    except:
                        # Try comma-separated
                        p['photos'] = [x.strip() for x in p['photos'].split(',') if x.strip()]
                elif not isinstance(p['photos'], list):
                    p['photos'] = []
        
        # Get first and last photos for before/after comparison
        first_progress = progress_data[-1] if progress_data else None
        latest_progress = progress_data[0] if progress_data else None
        
        return render_template('progress_tracking.html', 
                             member=member, 
                             progress_data=progress_data,
                             dates=dates,
                             weights=weights,
                             body_fat=body_fat,
                             muscle_mass=muscle_mass,
                             first_progress=first_progress,
                             latest_progress=latest_progress)
    except Exception as e:
        print(f"Error loading progress tracking: {e}")
        flash(f"Error loading progress: {str(e)}", "error")
        return redirect(url_for('all_members'))

@app.route('/progress_tracking/<int:member_id>/add', methods=['GET', 'POST'])
@login_required
def add_progress_entry(member_id):
    """Add a new progress entry for a member"""
    member = query_db('SELECT * FROM members WHERE id = %s', (member_id,), one=True)
    if not member:
        flash('Member not found!', 'error')
        return redirect(url_for('all_members'))
    
    if request.method == 'POST':
        try:
            tracking_date = request.form.get('tracking_date', '')
            weight = request.form.get('weight', '').strip()
            body_fat = request.form.get('body_fat', '').strip()
            muscle_mass = request.form.get('muscle_mass', '').strip()
            notes = request.form.get('notes', '').strip()
            tracked_by = session.get('username', 'Unknown')
            
            # Handle measurements JSON
            measurements = {}
            measurement_fields = ['chest', 'waist', 'hips', 'thigh', 'arm', 'neck']
            for field in measurement_fields:
                value = request.form.get(f'measurement_{field}', '').strip()
                if value:
                    measurements[field] = float(value)
            
            # Handle photo uploads
            uploaded_files = request.files.getlist('photos')
            photo_paths = []
            
            if uploaded_files:
                import uuid
                from werkzeug.utils import secure_filename
                import os
                
                upload_folder = os.path.join(app.root_path, 'static', 'progress_photos')
                os.makedirs(upload_folder, exist_ok=True)
                
                for file in uploaded_files:
                    if file and file.filename:
                        filename = secure_filename(file.filename)
                        unique_filename = f"{uuid.uuid4()}_{filename}"
                        filepath = os.path.join(upload_folder, unique_filename)
                        file.save(filepath)
                        photo_paths.append(f"progress_photos/{unique_filename}")
            
            # Prepare data for insertion
            measurements_json = Json(measurements) if measurements else None
            photos_array = photo_paths if photo_paths else None
            
            query_db(
                '''INSERT INTO progress_tracking 
                   (member_id, tracking_date, weight, body_fat, muscle_mass, measurements, photos, notes, tracked_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (member_id, tracking_date or datetime.now().date(),
                 float(weight) if weight else None,
                 float(body_fat) if body_fat else None,
                 float(muscle_mass) if muscle_mass else None,
                 measurements_json,
                 photos_array,  # PostgreSQL TEXT[] array
                 notes, tracked_by),
                commit=True
            )
            
            flash('Progress entry added successfully!', 'success')
            return redirect(url_for('progress_tracking', member_id=member_id))
        except Exception as e:
            print(f"Error adding progress entry: {e}")
            import traceback
            traceback.print_exc()
            flash(f"Error adding progress entry: {str(e)}", "error")
    
    # Get today's date for the form
    today = datetime.now().strftime('%Y-%m-%d')
    return render_template('add_progress_entry.html', member=member, today=today)

@app.route('/progress_tracking/<int:member_id>/<int:entry_id>/delete', methods=['POST'])
@login_required
def delete_progress_entry(member_id, entry_id):
    """Delete a progress entry"""
    try:
        entry = query_db(
            'SELECT photos FROM progress_tracking WHERE id = %s AND member_id = %s',
            (entry_id, member_id),
            one=True
        )
        
        if entry and entry.get('photos'):
            import os
            photos_list = entry['photos']
            # Handle different formats (list, string, etc.)
            if isinstance(photos_list, str):
                try:
                    photos_list = json.loads(photos_list)
                except:
                    # Try comma-separated or single path
                    photos_list = [x.strip() for x in photos_list.replace('[', '').replace(']', '').replace('"', '').split(',') if x.strip()]
            elif not isinstance(photos_list, list):
                photos_list = []
            
            for photo_path in photos_list:
                if photo_path:
                    full_path = os.path.join(app.root_path, 'static', photo_path)
                    if os.path.exists(full_path):
                        try:
                            os.remove(full_path)
                        except Exception as e:
                            print(f"Error deleting photo {photo_path}: {e}")
        
        query_db(
            'DELETE FROM progress_tracking WHERE id = %s AND member_id = %s',
            (entry_id, member_id),
            commit=True
        )
        
        flash('Progress entry deleted successfully!', 'success')
    except Exception as e:
        print(f"Error deleting progress entry: {e}")
        flash(f"Error deleting entry: {str(e)}", "error")
    
    return redirect(url_for('progress_tracking', member_id=member_id))

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

