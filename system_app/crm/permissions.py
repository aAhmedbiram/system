from functools import wraps
from flask import session, flash, redirect, url_for, request
from system_app.queries import query_db

# CRM Permissions List Constants
CRM_VIEW = 'crm_view'
CRM_CREATE = 'crm_create'
CRM_EDIT = 'crm_edit'
CRM_UPDATE_STAGE = 'crm_update_stage'
CRM_CONVERT = 'crm_convert'
CRM_ASSIGN = 'crm_assign'
CRM_ALL_LEADS = 'crm_all_leads'
CRM_CAMPAIGNS = 'crm_campaigns'
CRM_BULK_LEADS = 'crm_bulk_leads'

CRM_PERMISSIONS = {
    CRM_VIEW: "View CRM Dashboard and Assigned Leads",
    CRM_CREATE: "Create New Leads",
    CRM_EDIT: "Edit CRM Lead Profiles",
    CRM_UPDATE_STAGE: "Progress Lead Stages",
    CRM_CONVERT: "Convert Leads to Gym Members",
    CRM_ASSIGN: "Assign and Reassign CRM Leads",
    CRM_ALL_LEADS: "View and Edit All Leads (Unrestricted)",
    CRM_CAMPAIGNS: "Manage Marketing Outreach Campaigns",
    CRM_BULK_LEADS: "Bulk Leads"
}

def _load_permissions(permissions_val):
    if not permissions_val:
        return {}
    if isinstance(permissions_val, dict):
        return permissions_val
    import json
    try:
        return json.loads(permissions_val)
    except:
        return {}


def _user_requires_pending_approval(user):
    if not user:
        return False
    return bool(user.get('username') not in ['rino', 'ahmed_adel', 'malit_deng'] and not user.get('is_approved'))

def get_current_user():
    """Resolves and loads the current logged-in user with permission values."""
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

    if user.get('username') == 'rino':
        user['permissions'] = {'super_admin': True}
        return user

    user['permissions'] = _load_permissions(user.get('permissions'))
    return user

def login_required(f):
    """Decorator to enforce user login session presence."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('You must log in first!', 'error')
            return redirect(url_for('login'))
        user = get_current_user()
        if not user:
            session.clear()
            flash('Session expired. Please log in again.', 'error')
            return redirect(url_for('login'))
        if _user_requires_pending_approval(user):
            flash('Your account is pending approval.', 'error')
            return redirect(url_for('pending_approval'))
        return f(*args, **kwargs)
    return decorated_function

def crm_permission_required(permission_key):
    """Enforces specific CRM permission or super-admin access backend checks."""
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

            # Block other unapproved users from CRM
            if _user_requires_pending_approval(user):
                flash('Your account is pending Rino approval.', 'error')
                return redirect(url_for('pending_approval'))

            perms = user.get('permissions') or {}
            # Allow if they have the specific permission OR if they are a super_admin
            if not perms.get(permission_key) and not perms.get('super_admin'):
                flash('You do not have permission to access this page!', 'error')
                referrer = request.referrer
                if referrer and referrer != request.url:
                    return redirect(referrer)
                return redirect(url_for('attendance_table'))

            return f(*args, **kwargs)
        return wrapped
    return decorator

def can_view_all_leads(user):
    """Visibility authorization rule checks."""
    if not user:
        return False
    username = user.get('username')
    if username == 'rino':
        return True
    perms = user.get('permissions') or {}
    return perms.get('super_admin') or perms.get(CRM_ALL_LEADS)
