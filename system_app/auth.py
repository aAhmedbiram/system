"""Shared authentication lookup helpers used by all protected modules."""

import json

from flask import current_app, jsonify, session

from .queries import query_db


class CurrentUserLookupError(RuntimeError):
    """The authenticated user's database state could not be determined."""


def _authentication_unavailable_response():
    """Return a generic retryable response without exposing database details."""
    return jsonify({
        'error': 'authentication_temporarily_unavailable',
        'message': 'Authentication is temporarily unavailable. Please try again.',
    }), 503


def _load_permissions(raw_permissions):
    """Safely load permissions from DB (JSONB or TEXT) into a dict."""
    if not raw_permissions:
        perms = {}
    elif isinstance(raw_permissions, dict):
        perms = raw_permissions
    else:
        try:
            perms = json.loads(raw_permissions)
        except Exception:
            perms = {}

    if perms.get('invitations'):
        perms.setdefault('invitations_view', True)
        perms.setdefault('invitations_use', True)
    return perms


def get_default_permissions_for_username(username):
    """Return the existing default permission set for a username."""
    username = (username or '').strip()
    if username == 'rino':
        return {'super_admin': True}

    base = {
        'index': True, 'attendance': True, 'delete_attendance': True,
        'members_view': True, 'members_edit': True, 'delete_member': True,
        'training_templates': True, 'offers': True, 'renewal_log': True,
        'supplements_water': True, 'attendance_backup': True,
        'undo_action': True, 'data_management': True, 'online_users': True,
        'invoices': True, 'invitations': True, 'invitations_view': True,
        'invitations_use': True,
    }
    if username == 'ahmed_adel':
        base.update({
            'delete_member': False, 'undo_action': False, 'data_management': False,
            'online_users': False, 'training_templates': False, 'offers': False,
            'renewal_log': False, 'delete_attendance': False,
        })
        return base
    if username == 'malit_deng':
        base.update({
            'delete_member': False, 'undo_action': False, 'data_management': False,
            'online_users': False, 'training_templates': False, 'offers': False,
            'renewal_log': False, 'supplements_water': False,
            'attendance_backup': False, 'delete_attendance': False,
        })
        return base
    return {'attendance': True}


def get_current_user(query_executor=None):
    """Return a user, None only for no session or a confirmed missing row."""
    user_id = session.get('user_id')
    if not user_id:
        return None
    query_executor = query_executor or query_db
    try:
        user = query_executor(
            'SELECT id, username, email, is_approved, permissions FROM users WHERE id = %s',
            (user_id,), one=True,
        )
        if not user:
            return None
        if user.get('username') == 'rino':
            user['permissions'] = {'super_admin': True}
            return user
        perms = _load_permissions(user.get('permissions'))
        user['permissions'] = perms or get_default_permissions_for_username(user.get('username'))
        return user
    except Exception as exc:
        current_app.logger.warning(
            'current_user_lookup_failed user_id=%s error_type=%s',
            user_id, type(exc).__name__, exc_info=True,
        )
        raise CurrentUserLookupError from exc
