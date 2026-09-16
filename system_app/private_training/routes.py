from __future__ import annotations

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for, jsonify
import psycopg2

from system_app.crm.permissions import get_current_user, login_required
from system_app.func import get_cairo_date
from system_app.queries import query_db

from .permissions import (
    can_manage_private_training,
    can_train_private_training,
    can_view_private_training,
    has_private_training_permission,
    is_approved_user,
    is_super_user,
)
from .services import (
    PrivateTrainingCancelledError,
    PrivateTrainingConflictError,
    PrivateTrainingCompletedError,
    PrivateTrainingError,
    PrivateTrainingExpiredError,
    PrivateTrainingForbiddenError,
    PrivateTrainingAlreadyProcessedError,
    PrivateTrainingInvalidTrainerError,
    PrivateTrainingNotFoundError,
    PrivateTrainingPendingSessionConflictError,
    PrivateTrainingSubscriptionConflictError,
    PrivateTrainingValidationError,
    PrivateTrainingFeatureUnavailableError,
    PrivateTrainingPhoneError,
    create_private_training_subscription,
    create_private_training_session_checkin,
    create_private_training_checkin_invitation,
    cancel_private_training_subscription,
    generate_portal_token,
    get_private_subscription_for_trainer,
    get_private_training_subscription,
    get_private_training_pending_session,
    list_private_clients_for_trainer,
    list_private_training_trainer_options,
    list_private_training_sessions,
    revoke_portal_token,
)

private_training_bp = Blueprint("private_training", __name__)


def _checkin_wants_json() -> bool:
    """Return true only for an explicit progressive-enhancement request."""
    if request.headers.get("X-Requested-With", "").lower() == "xmlhttprequest":
        return True
    return request.accept_mimetypes["application/json"] > request.accept_mimetypes["text/html"]


def _checkin_json_error(error_code: str, message: str, status_code: int):
    return jsonify({"ok": False, "error": error_code, "message": message}), status_code


def _iso_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def _checkin_json_success(current_user, subscription, session_row):
    sessions = list_private_training_sessions(subscription["id"])
    return jsonify({
        "ok": True,
        "message": "Private training session check-in created successfully.",
        "subscription": {
            "id": subscription["id"],
            "total_sessions": int(subscription.get("total_sessions") or 0),
            "approved_sessions": int(subscription.get("approved_count") or 0),
            "remaining_sessions": int(subscription.get("remaining_sessions") or 0),
            "pending_sessions": int(subscription.get("pending_count") or 0),
            "effective_status": subscription.get("effective_status"),
        },
        "session": {
            "id": session_row.get("id"),
            "trainer": session_row.get("trainer_display_name") or current_user.get("username"),
            "checked_in_at": _iso_value(session_row.get("checked_in_at")),
            "workout_name": session_row.get("workout_name"),
            "status": session_row.get("status"),
            "approved_at": _iso_value(session_row.get("approved_at")),
        },
        "sessions": [
            {
                "id": row.get("id"),
                "trainer": row.get("trainer_display_name") or row.get("trainer_username"),
                "checked_in_at": _iso_value(row.get("checked_in_at")),
                "workout_name": row.get("workout_name"),
                "status": row.get("status"),
                "approved_at": _iso_value(row.get("approved_at")),
            }
            for row in sessions
        ],
    })


def _checkin_exception_response(exc):
    if isinstance(exc, PrivateTrainingFeatureUnavailableError):
        return _checkin_json_error("feature_unavailable", "WhatsApp invitations are temporarily unavailable.", 503)
    if isinstance(exc, PrivateTrainingPhoneError):
        return _checkin_json_error(exc.error_code, str(exc), 422)
    if getattr(exc, "error_code", None) == "invalid_operation_id":
        return _checkin_json_error("invalid_operation_id", "The check-in operation id is invalid.", 400)
    if isinstance(exc, PrivateTrainingValidationError):
        return _checkin_json_error("validation_error", "Please enter a valid workout name.", 400)
    if isinstance(exc, PrivateTrainingPendingSessionConflictError):
        return _checkin_json_error("pending_session_exists", str(exc), 409)
    if isinstance(exc, PrivateTrainingCancelledError):
        return _checkin_json_error("cancelled_subscription", str(exc), 409)
    if isinstance(exc, PrivateTrainingExpiredError):
        return _checkin_json_error("expired_subscription", str(exc), 409)
    if isinstance(exc, PrivateTrainingCompletedError):
        return _checkin_json_error("no_remaining_sessions", str(exc), 409)
    if isinstance(exc, PrivateTrainingNotFoundError):
        return _checkin_json_error("subscription_not_found", str(exc), 404)
    if isinstance(exc, PrivateTrainingForbiddenError):
        return _checkin_json_error("forbidden", str(exc), 403)
    if isinstance(exc, PrivateTrainingConflictError):
        return _checkin_json_error("inactive_subscription", str(exc), 409)
    return None


def _whatsapp_message(subscription, session, portal_url):
    def clean(value):
        return " ".join(str(value or "").split())
    trainer_name = clean(
        subscription.get("trainer_display_name") or subscription.get("trainer_username")
    )
    if trainer_name:
        if trainer_name.casefold().startswith("c."):
            trainer_name = trainer_name[2:].strip()
        trainer_line = f"\nالمدرب: \u200eC. {trainer_name}"
    else:
        trainer_line = ""
    return (
        f"مرحبًا {clean(subscription.get('client_name'))} 👋\n\n"
        "تم تسجيل جلسة الـ Private Training الخاصة بك.\n"
        f"التمرين: {clean(session.get('workout_name'))}\n"
        f"{trainer_line}\n\n"
        "برجاء فتح الرابط التالي ومراجعة الجلسة وتأكيدها:\n"
        f"{portal_url}\n\nRival Gym 💪"
    )


def _checkin_invitation_json_success(result):
    from urllib.parse import urlencode
    subscription = result["subscription"]
    session = result["session"]
    portal_url = url_for("private_training_public.member_portal", raw_token=result["raw_token"], _external=True)
    message = _whatsapp_message(subscription, session, portal_url)
    whatsapp_url = "https://wa.me/{}?{}".format(result["phone"], urlencode({"text": message}))
    return jsonify({
        "ok": True, "message": "Session created and WhatsApp invitation prepared.",
        "replayed": bool(result.get("replayed")),
        "subscription": {
            "approved_sessions": int(subscription.get("approved_count") or 0),
            "remaining_sessions": int(subscription.get("remaining_sessions") or 0),
            "pending_sessions": int(subscription.get("pending_count") or 0),
            "effective_status": subscription.get("effective_status"),
        },
        "session": {
            "id": session.get("id"), "trainer": session.get("trainer_display_name"),
            "checked_in_at": _iso_value(session.get("checked_in_at")),
            "workout_name": session.get("workout_name"), "status": session.get("status"),
            "approved_at": _iso_value(session.get("approved_at")),
        },
        "whatsapp": {"url": whatsapp_url},
    })


def _json_login_redirect_boundary(view):
    """Convert only login redirects to JSON; preserve all normal redirects."""
    from functools import wraps

    @wraps(view)
    def wrapped(*args, **kwargs):
        response = view(*args, **kwargs)
        if _checkin_wants_json() and getattr(response, "status_code", None) in {301, 302, 303, 307, 308}:
            location = response.headers.get("Location", "")
            if location.endswith("/login") or "/login?" in location:
                return _checkin_json_error("unauthorized", "Your session has expired. Please log in again.", 401)
        return response

    return wrapped


def _common_context():
    from system_app.app import get_common_template_context

    return get_common_template_context()


def _render(template_name: str, **context):
    merged = _common_context()
    merged.update(context)
    return render_template(template_name, **merged)


def _current_user_or_redirect():
    current_user = get_current_user()
    if not current_user:
        flash("You must log in first!", "error")
        return None, redirect(url_for("login"))
    if not is_approved_user(current_user):
        flash("Your account is pending approval.", "error")
        return None, redirect(url_for("pending_approval"))
    return current_user, None


def _is_manage_authorized(current_user):
    return bool(current_user) and (is_super_user(current_user) or can_manage_private_training(current_user))


def _is_trainer_authorized(current_user):
    return bool(current_user) and can_train_private_training(current_user)


def _member_link(raw_token: str) -> str:
    return url_for("private_training_public.member_portal", raw_token=raw_token, _external=True)


def _subscription_ownership_context(current_user, subscription):
    owns_subscription = bool(subscription and current_user and subscription.get("trainer_user_id") == current_user.get("id"))
    trainer_authorized = bool(current_user) and can_train_private_training(current_user)
    super_admin = bool(current_user) and is_super_user(current_user)
    portal_can_manage = bool(super_admin or (trainer_authorized and owns_subscription))
    return {
        "owns_subscription": owns_subscription,
        "is_trainer_owner": owns_subscription and trainer_authorized,
        "portal_can_manage": portal_can_manage,
        "can_manage_tokens": portal_can_manage,
        "can_check_in": bool(
            subscription
            and portal_can_manage
            and str(subscription.get("effective_status") or "").upper() == "ACTIVE"
            and int(subscription.get("remaining_sessions") or 0) > 0
            and int(subscription.get("pending_count") or 0) == 0
        ),
    }


def _check_in_status_message(subscription):
    if not subscription:
        return None
    if int(subscription.get("pending_count") or 0) > 0:
        return "Waiting for Member Approval"
    effective_status = str(subscription.get("effective_status") or "").upper()
    if effective_status == "ASSIGNED":
        return "Private training has not started yet"
    if effective_status == "EXPIRED":
        return "Private training is expired"
    if effective_status == "COMPLETED":
        return "Private training is completed"
    if effective_status == "CANCELLED":
        return "Private training is cancelled"
    if int(subscription.get("remaining_sessions") or 0) <= 0:
        return "No remaining sessions"
    return None


def _active_member_filter_sql():
    return """
        end_date IS NOT NULL
        AND btrim(COALESCE(end_date, '')) <> ''
        AND LENGTH(btrim(end_date)) >= 10
        AND SUBSTRING(btrim(end_date), 1, 10) ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}$'
        AND CAST(SUBSTRING(btrim(end_date), 1, 10) AS DATE) >= %s
        AND COALESCE(membership_status, '') <> 'EX'
    """


def _load_member_options(member_query: str | None = None):
    query = (member_query or "").strip()
    today = get_cairo_date()
    base_select = """
        SELECT id, name, phone, membership_packages, membership_status, starting_date, end_date
        FROM members
    """
    active_clause = _active_member_filter_sql()
    if not query:
        members = query_db(
            f"""
            {base_select}
            WHERE {active_clause}
            ORDER BY name ASC, id ASC
            """,
            (today,),
        ) or []
        return [dict(row) for row in members]

    like_query = f"%{query}%"
    params = [today]
    where_parts = [active_clause]
    order_clause = "ORDER BY name ASC, id ASC"

    if query.isdigit():
        where_parts.append("(CAST(id AS TEXT) = %s OR name ILIKE %s OR COALESCE(phone, '') ILIKE %s)")
        params.extend([query, like_query, like_query])
        order_clause = """
            ORDER BY
                CASE
                    WHEN CAST(id AS TEXT) = %s THEN 0
                    WHEN name ILIKE %s THEN 1
                    WHEN COALESCE(phone, '') ILIKE %s THEN 2
                    ELSE 3
                END,
                name ASC,
                id ASC
        """
        params.extend([query, like_query, like_query])
    else:
        where_parts.append("(name ILIKE %s OR COALESCE(phone, '') ILIKE %s)")
        params.extend([like_query, like_query])
        order_clause = """
            ORDER BY
                CASE
                    WHEN name ILIKE %s THEN 0
                    WHEN COALESCE(phone, '') ILIKE %s THEN 1
                    ELSE 2
                END,
                name ASC,
                id ASC
        """
        params.extend([like_query, like_query])

    members = query_db(
        f"""
        {base_select}
        WHERE {' AND '.join(where_parts)}
        {order_clause}
        """,
        tuple(params),
    ) or []
    return [dict(row) for row in members]


def _load_trainer_options():
    users = query_db(
        """
        SELECT id, username, email, is_approved, permissions
        FROM users
        WHERE is_approved = TRUE
        ORDER BY username ASC, id ASC
        """,
    ) or []
    trainers = []
    for row in users:
        row_dict = dict(row)
        if can_train_private_training(row_dict):
            trainers.append(row_dict)
    return trainers


def _portal_action_permissions(current_user, subscription):
    owns_subscription = bool(subscription and subscription.get("trainer_user_id") == current_user.get("id"))
    can_manage_tokens = bool(is_super_user(current_user) or (can_train_private_training(current_user) and owns_subscription))
    return {
        "can_manage_tokens": can_manage_tokens,
    }


def _can_view_all_subscriptions(current_user):
    return bool(
        current_user
        and (
            is_super_user(current_user)
            or can_manage_private_training(current_user)
            or has_private_training_permission(current_user, "private_training_view")
        )
    )


def _load_subscription_or_redirect(current_user, subscription_id):
    try:
        subscription = get_private_subscription_for_trainer(current_user, subscription_id)
        return subscription, None
    except PrivateTrainingNotFoundError:
        flash("Private training subscription not found.", "error")
        return None, redirect(url_for("private_training.subscription_list"))
    except PrivateTrainingForbiddenError:
        flash("You cannot access that private training subscription.", "error")
        if can_train_private_training(current_user):
            return None, redirect(url_for("private_training.my_clients"))
        return None, redirect(url_for("private_training.subscription_list"))


def _filter_subscription_rows(rows, status=None):
    filtered = []
    status = str(status or "").strip().upper()
    for row in rows:
        row_dict = dict(row)
        if status and str(row_dict.get("effective_status") or row_dict.get("status") or "").upper() != status:
            continue
        filtered.append(row_dict)
    return filtered


def _subscription_list_context(
    current_user,
    *,
    workspace_title: str,
    is_trainer_workspace: bool,
    allow_create: bool,
    show_all_subscriptions_link: bool = False,
):
    trainer_user_id = (request.args.get("trainer_user_id") or "").strip()
    if trainer_user_id and not trainer_user_id.isdigit():
        trainer_user_id = ""
    client_type = (request.args.get("client_type") or "").strip().upper()
    if client_type not in ("", "MEMBER", "OUTCOMER"):
        client_type = ""
    status = request.args.get("status")
    rows = list_private_clients_for_trainer(
        current_user,
        trainer_user_id=trainer_user_id,
        client_type=client_type,
    )
    rows = _filter_subscription_rows(rows, status=status)
    return _render(
        "private_training/subscriptions_list.html",
        current_user=current_user,
        workspace_title=workspace_title,
        is_trainer_workspace=is_trainer_workspace,
        allow_create=allow_create,
        show_all_subscriptions_link=show_all_subscriptions_link,
        subscriptions=rows,
        trainer_options=list_private_training_trainer_options(current_user),
        active_filters={
            "trainer_user_id": trainer_user_id or "",
            "client_type": client_type or "",
            "status": status or "",
        },
    )


@private_training_bp.route("/")
@login_required
def dashboard():
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if _is_manage_authorized(current_user) or can_view_private_training(current_user):
        return redirect(url_for("private_training.subscription_list"))
    if _is_trainer_authorized(current_user):
        return redirect(url_for("private_training.my_clients"))
    flash("You do not have access to private training.", "error")
    return redirect(url_for("attendance_table"))


@private_training_bp.route("/subscriptions")
@login_required
def subscription_list():
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if not (_is_manage_authorized(current_user) or can_view_private_training(current_user)):
        if _is_trainer_authorized(current_user):
            return redirect(url_for("private_training.my_clients"))
        flash("You do not have access to the private training list.", "error")
        return redirect(url_for("attendance_table"))
    return _subscription_list_context(
        current_user,
        workspace_title="Private Training Subscriptions",
        is_trainer_workspace=False,
        allow_create=_is_manage_authorized(current_user),
    )


@private_training_bp.route("/my-clients")
@login_required
def my_clients():
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if not _is_trainer_authorized(current_user):
        if _is_manage_authorized(current_user) or can_view_private_training(current_user):
            return redirect(url_for("private_training.subscription_list"))
        flash("You do not have access to the trainer workspace.", "error")
        return redirect(url_for("attendance_table"))
    return _subscription_list_context(
        current_user,
        workspace_title="My Private Clients",
        is_trainer_workspace=True,
        allow_create=False,
        show_all_subscriptions_link=_can_view_all_subscriptions(current_user),
    )


@private_training_bp.route("/subscriptions/new", methods=["GET"])
@login_required
def new_subscription():
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if not _is_manage_authorized(current_user):
        flash("You do not have permission to create private training subscriptions.", "error")
        return redirect(url_for("private_training.subscription_list" if can_view_private_training(current_user) else "attendance_table"))

    member_query = request.args.get("q", "")
    client_type = (request.args.get("client_type", "MEMBER") or "MEMBER").strip().upper()
    selected_member_id = request.args.get("member_id", "").strip() if client_type == "MEMBER" else ""
    client_name = request.args.get("client_name", "").strip()
    client_phone = request.args.get("client_phone", "").strip()
    members = _load_member_options(member_query)
    trainers = _load_trainer_options()
    return _render(
        "private_training/create_subscription.html",
        current_user=current_user,
        members=members,
        trainers=trainers,
        selected_member_id=selected_member_id,
        member_query=member_query,
        form_data={
            "client_type": client_type,
            "client_name": client_name,
            "client_phone": client_phone,
        },
    )


@private_training_bp.route("/subscriptions", methods=["POST"])
@login_required
def create_subscription():
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if not _is_manage_authorized(current_user):
        flash("You do not have permission to create private training subscriptions.", "error")
        return redirect(url_for("private_training.subscription_list" if can_view_private_training(current_user) else "attendance_table"))

    member_query = request.form.get("member_query", "")
    members = _load_member_options(member_query)
    trainers = _load_trainer_options()
    client_type = (request.form.get("client_type", "MEMBER") or "MEMBER").strip().upper()
    form_data = {
        "client_type": client_type,
        "member_id": request.form.get("member_id", "").strip(),
        "trainer_user_id": request.form.get("trainer_user_id", "").strip(),
        "total_sessions": request.form.get("total_sessions", "").strip(),
        "private_start_date": request.form.get("private_start_date", "").strip(),
        "private_expiry_date": request.form.get("private_expiry_date", "").strip(),
        "client_name": request.form.get("client_name", "").strip(),
        "client_phone": request.form.get("client_phone", "").strip(),
    }

    try:
        result = create_private_training_subscription(
            current_user,
            form_data["member_id"],
            form_data["trainer_user_id"],
            form_data["total_sessions"],
            form_data["private_start_date"],
            form_data["private_expiry_date"],
            client_type=form_data["client_type"],
            client_name=form_data["client_name"],
            client_phone=form_data["client_phone"],
        )
        subscription = result["subscription"]
        flash("Private training subscription created successfully.", "success")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription["id"]))
    except PrivateTrainingInvalidTrainerError as exc:
        flash(str(exc), "error")
        return _render(
            "private_training/create_subscription.html",
            current_user=current_user,
            members=members,
            trainers=trainers,
            selected_member_id=form_data["member_id"] if form_data["client_type"] == "MEMBER" else "",
            member_query=member_query,
            form_data=form_data,
            error_message=str(exc),
        ), 400
    except (
        PrivateTrainingNotFoundError,
        PrivateTrainingValidationError,
        PrivateTrainingSubscriptionConflictError,
        PrivateTrainingExpiredError,
    ) as exc:
        flash(str(exc), "error")
        status_code = 400
        if isinstance(exc, PrivateTrainingSubscriptionConflictError):
            status_code = 409
        elif isinstance(exc, PrivateTrainingExpiredError):
            status_code = 400
        return _render(
            "private_training/create_subscription.html",
            current_user=current_user,
            members=members,
            trainers=trainers,
            selected_member_id=form_data["member_id"] if form_data["client_type"] == "MEMBER" else "",
            member_query=member_query,
            form_data=form_data,
            error_message=str(exc),
        ), status_code
    except PrivateTrainingForbiddenError as exc:
        flash(str(exc), "error")
        return redirect(url_for("attendance_table"))
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
        return _render(
            "private_training/create_subscription.html",
            current_user=current_user,
            members=members,
            trainers=trainers,
            selected_member_id=form_data["member_id"] if form_data["client_type"] == "MEMBER" else "",
            member_query=member_query,
            form_data=form_data,
            error_message=str(exc),
        ), 400


@private_training_bp.route("/subscriptions/<int:subscription_id>")
@login_required
def subscription_detail(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    subscription, response = _load_subscription_or_redirect(current_user, subscription_id)
    if response:
        return response
    sessions = list_private_training_sessions(subscription_id)
    portal_link_status = "Active link exists" if int(subscription.get("active_token_count") or 0) > 0 else "No active token"
    pending_session = get_private_training_pending_session(subscription_id)
    ownership_context = _subscription_ownership_context(current_user, subscription)
    can_cancel_subscription = bool(
        _is_manage_authorized(current_user)
        and str(subscription.get("effective_status") or "").upper() in {"ASSIGNED", "ACTIVE"}
    )
    return _render(
        "private_training/subscription_detail.html",
        current_user=current_user,
        subscription=subscription,
        sessions=sessions,
        pending_session=pending_session,
        portal_link_status=portal_link_status,
        generated_portal_url=None,
        generated_portal_token=None,
        show_generate_result=False,
        check_in_status_message=_check_in_status_message(subscription),
        can_cancel_subscription=can_cancel_subscription,
        private_training_whatsapp_checkin_enabled=bool(current_app.config.get("PRIVATE_TRAINING_WHATSAPP_CHECKIN_ENABLED")),
        **ownership_context,
    )


@private_training_bp.route("/subscriptions/<int:subscription_id>/portal-token", methods=["POST"])
@login_required
def generate_subscription_portal_token(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    subscription, response = _load_subscription_or_redirect(current_user, subscription_id)
    if response:
        return response
    try:
        result = generate_portal_token(current_user, subscription_id)
        token_row = result["token"]
        raw_token = result["raw_token"]
        subscription = result["subscription"]
        sessions = list_private_training_sessions(subscription_id)
        portal_url = _member_link(raw_token)
        flash("Member portal link generated successfully.", "success")
        pending_session = get_private_training_pending_session(subscription_id)
        ownership_context = _subscription_ownership_context(current_user, subscription)
        return _render(
            "private_training/subscription_detail.html",
            current_user=current_user,
            subscription=subscription,
            sessions=sessions,
            pending_session=pending_session,
            portal_link_status="Active link exists",
            generated_portal_url=portal_url,
            generated_portal_token=raw_token,
            generated_token_id=token_row.get("id"),
            show_generate_result=True,
            check_in_status_message=_check_in_status_message(subscription),
            **ownership_context,
        )
    except PrivateTrainingForbiddenError as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (PrivateTrainingCompletedError, PrivateTrainingExpiredError, PrivateTrainingCancelledError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))


@private_training_bp.route("/subscriptions/<int:subscription_id>/portal-token/revoke", methods=["POST"])
@login_required
def revoke_subscription_portal_token(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    subscription, response = _load_subscription_or_redirect(current_user, subscription_id)
    if response:
        return response
    try:
        revoke_portal_token(current_user, subscription_id)
        flash("Member portal link revoked successfully.", "success")
    except PrivateTrainingForbiddenError as exc:
        flash(str(exc), "error")
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
    return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))


@private_training_bp.route("/subscriptions/<int:subscription_id>/cancel", methods=["POST"])
@login_required
def cancel_subscription(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    if not _is_manage_authorized(current_user):
        flash("You do not have permission to cancel private training subscriptions.", "error")
        return redirect(url_for("attendance_table"))
    try:
        cancel_private_training_subscription(current_user, subscription_id)
        flash("Private training subscription cancelled successfully.", "success")
    except PrivateTrainingNotFoundError as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_list"))
    except (PrivateTrainingCancelledError, PrivateTrainingCompletedError, PrivateTrainingExpiredError) as exc:
        flash(str(exc), "error")
    except PrivateTrainingForbiddenError as exc:
        flash(str(exc), "error")
        return redirect(url_for("attendance_table"))
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
    return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))


@private_training_bp.route("/subscriptions/<int:subscription_id>/check-in", methods=["POST"])
@_json_login_redirect_boundary
@login_required
def check_in_subscription(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    workout_name = request.form.get("workout_name")
    try:
        if current_app.config.get("PRIVATE_TRAINING_WHATSAPP_CHECKIN_ENABLED") and _checkin_wants_json():
            result = create_private_training_checkin_invitation(
                current_user, subscription_id, workout_name,
                request.form.get("client_operation_id"),
                current_app.config.get("PRIVATE_TRAINING_PORTAL_TOKEN_SIGNING_KEY", ""),
            )
            return _checkin_invitation_json_success(result)
        result = create_private_training_session_checkin(current_user, subscription_id, workout_name)
        if _checkin_wants_json():
            subscription = get_private_training_subscription(subscription_id)
            return _checkin_json_success(current_user, subscription, result)
        flash("Private training session check-in created successfully.", "success")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except PrivateTrainingPendingSessionConflictError as exc:
        if _checkin_wants_json():
            return _checkin_exception_response(exc)
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (PrivateTrainingCancelledError, PrivateTrainingCompletedError, PrivateTrainingExpiredError, PrivateTrainingConflictError) as exc:
        if _checkin_wants_json():
            return _checkin_exception_response(exc)
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (PrivateTrainingForbiddenError, PrivateTrainingNotFoundError) as exc:
        if _checkin_wants_json():
            return _checkin_exception_response(exc)
        flash(str(exc), "error")
        if can_train_private_training(current_user):
            return redirect(url_for("private_training.my_clients"))
        return redirect(url_for("private_training.subscription_list"))
    except PrivateTrainingError as exc:
        if _checkin_wants_json():
            return _checkin_exception_response(exc)
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (psycopg2.OperationalError, psycopg2.InterfaceError):
        if _checkin_wants_json():
            return _checkin_json_error(
                "temporary_database_error",
                "The result could not be confirmed. Check Session History before trying again.",
                503,
            )
        raise
    except psycopg2.Error:
        if _checkin_wants_json():
            return _checkin_json_error(
                "temporary_database_error",
                "The result could not be confirmed. Check Session History before trying again.",
                503,
            )
        raise
