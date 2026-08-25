from __future__ import annotations

from urllib.parse import urljoin

from flask import Blueprint, flash, redirect, render_template, request, url_for

from system_app.crm.permissions import get_current_user, login_required
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
    PrivateTrainingCompletedError,
    PrivateTrainingError,
    PrivateTrainingExpiredError,
    PrivateTrainingForbiddenError,
    PrivateTrainingInvalidTrainerError,
    PrivateTrainingNotFoundError,
    PrivateTrainingSubscriptionConflictError,
    PrivateTrainingValidationError,
    create_private_training_subscription,
    generate_portal_token,
    get_private_subscription_for_trainer,
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
        flash("Your account is pending Rino approval.", "error")
        return None, redirect(url_for("attendance_table"))
    return current_user, None


def _is_manage_authorized(current_user):
    return bool(current_user) and (is_super_user(current_user) or can_manage_private_training(current_user))


def _is_trainer_authorized(current_user):
    return bool(current_user) and can_train_private_training(current_user)


def _member_link(raw_token: str) -> str:
    return urljoin((request.host_url or "").rstrip("/") + "/", f"private-training/member/{raw_token}")


def _load_member_options(member_query: str | None = None):
    members = query_db(
        """
        SELECT id, name, phone, membership_packages, membership_status, starting_date, end_date
        FROM members
        ORDER BY name ASC, id DESC
        """,
    ) or []
    query = (member_query or "").strip().lower()
    if not query:
        return [dict(row) for row in members]
    filtered = []
    for row in members:
        row_dict = dict(row)
        searchable = " ".join(
            str(row_dict.get(key) or "")
            for key in ("id", "name", "phone", "membership_packages", "membership_status")
        ).lower()
        if query in searchable:
            filtered.append(row_dict)
    return filtered


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
    portal_permissions = _portal_action_permissions(current_user, subscription)
    return _render(
        "private_training/subscription_detail.html",
        current_user=current_user,
        subscription=subscription,
        sessions=sessions,
        portal_link_status=portal_link_status,
        generated_portal_url=None,
        generated_portal_token=None,
        show_generate_result=False,
        **portal_permissions,
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
        portal_permissions = _portal_action_permissions(current_user, subscription)
        return _render(
            "private_training/subscription_detail.html",
            current_user=current_user,
            subscription=subscription,
            sessions=sessions,
            portal_link_status="Active link exists",
            generated_portal_url=portal_url,
            generated_portal_token=raw_token,
            generated_token_id=token_row.get("id"),
            show_generate_result=True,
            **portal_permissions,
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
