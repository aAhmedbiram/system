from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

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
    create_private_training_subscription,
    create_private_training_session_checkin,
    cancel_private_training_subscription,
    generate_portal_token,
    get_private_subscription_for_trainer,
    get_private_training_pending_session,
    list_private_clients_for_trainer,
    list_private_training_sessions,
    revoke_portal_token,
)

private_training_bp = Blueprint("private_training", __name__)


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


def _filter_subscription_rows(rows, trainer_user_id=None, status=None):
    filtered = []
    trainer_user_id = str(trainer_user_id or "").strip()
    status = str(status or "").strip().upper()
    for row in rows:
        row_dict = dict(row)
        if trainer_user_id and str(row_dict.get("trainer_user_id")) != trainer_user_id:
            continue
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
    rows = list_private_clients_for_trainer(current_user)
    trainer_user_id = request.args.get("trainer_user_id")
    status = request.args.get("status")
    rows = _filter_subscription_rows(rows, trainer_user_id=trainer_user_id, status=status)
    return _render(
        "private_training/subscriptions_list.html",
        current_user=current_user,
        workspace_title=workspace_title,
        is_trainer_workspace=is_trainer_workspace,
        allow_create=allow_create,
        show_all_subscriptions_link=show_all_subscriptions_link,
        subscriptions=rows,
        active_filters={
            "trainer_user_id": trainer_user_id or "",
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
    selected_member_id = request.args.get("member_id", "").strip()
    members = _load_member_options(member_query)
    trainers = _load_trainer_options()
    return _render(
        "private_training/create_subscription.html",
        current_user=current_user,
        members=members,
        trainers=trainers,
        selected_member_id=selected_member_id,
        member_query=member_query,
        form_data={},
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
    form_data = {
        "member_id": request.form.get("member_id", "").strip(),
        "trainer_user_id": request.form.get("trainer_user_id", "").strip(),
        "total_sessions": request.form.get("total_sessions", "").strip(),
        "private_start_date": request.form.get("private_start_date", "").strip(),
        "private_expiry_date": request.form.get("private_expiry_date", "").strip(),
    }

    try:
        result = create_private_training_subscription(
            current_user,
            form_data["member_id"],
            form_data["trainer_user_id"],
            form_data["total_sessions"],
            form_data["private_start_date"],
            form_data["private_expiry_date"],
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
            selected_member_id=form_data["member_id"],
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
            selected_member_id=form_data["member_id"],
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
            selected_member_id=form_data["member_id"],
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
@login_required
def check_in_subscription(subscription_id: int):
    current_user, response = _current_user_or_redirect()
    if response:
        return response
    try:
        result = create_private_training_session_checkin(current_user, subscription_id)
        flash("Private training session check-in created successfully.", "success")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except PrivateTrainingPendingSessionConflictError as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (PrivateTrainingCancelledError, PrivateTrainingCompletedError, PrivateTrainingExpiredError, PrivateTrainingConflictError) as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
    except (PrivateTrainingForbiddenError, PrivateTrainingNotFoundError) as exc:
        flash(str(exc), "error")
        if can_train_private_training(current_user):
            return redirect(url_for("private_training.my_clients"))
        return redirect(url_for("private_training.subscription_list"))
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
        return redirect(url_for("private_training.subscription_detail", subscription_id=subscription_id))
