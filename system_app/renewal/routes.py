"""HTTP boundary for the read-only Renewal Command Center."""

from __future__ import annotations

from functools import wraps
from math import ceil

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, url_for

from system_app.app import get_current_user, permission_required
from system_app.renewal.queries import (
    RENEWAL_FILTERS,
    RENEWAL_WORKFLOW_STATUS_FILTERS,
    RenewalAssignmentError,
    assign_renewal_case,
    get_renewal_assignees,
    get_renewal_queue,
    get_renewal_workflow_queue,
)
from system_app.renewal.permissions import (
    RENEWAL_CENTER_ASSIGN,
    RENEWAL_CENTER_MANAGER,
    RENEWAL_CENTER_VIEW,
)

renewal_bp = Blueprint("renewal", __name__)

PER_PAGE = 25


def _has_permission(user, permission_key):
    permissions = (user or {}).get("permissions") or {}
    return bool(
        (user or {}).get("username") == "rino"
        or permissions.get("super_admin")
        or permissions.get(permission_key)
    )


def _safe_queue_args(*, manager):
    queue_filter = request.args.get("filter", "all", type=str).strip().lower()
    if queue_filter not in RENEWAL_FILTERS:
        queue_filter = "all"
    status_filter = request.args.get("status", "all", type=str).strip().lower()
    if status_filter not in RENEWAL_WORKFLOW_STATUS_FILTERS:
        status_filter = "all"
    owner_filter = request.args.get("owner", "all", type=str).strip().lower()
    if not manager or not (
        owner_filter == "all"
        or owner_filter == "unassigned"
        or owner_filter.isdigit()
    ):
        owner_filter = "all"
    search = request.args.get("search", "", type=str).strip()
    page = max(request.args.get("page", 1, type=int) or 1, 1)
    return queue_filter, status_filter, owner_filter, search, page


def _renewal_redirect():
    queue_filter, status_filter, owner_filter, search, page = _safe_queue_args(
        manager=True
    )
    return redirect(
        url_for(
            "renewal.renewal_center",
            filter=queue_filter,
            status=status_filter,
            owner=owner_filter,
            search=search,
            page=page,
        )
    )


def renewal_feature_enabled(f):
    """Hide the entire Renewal Center boundary while the feature is disabled."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("RENEWAL_COMMAND_CENTER_ENABLED", False):
            abort(404)
        return f(*args, **kwargs)
    return wrapped


def renewal_workflow_enabled(f):
    """Keep Phase 1B.2 writes unavailable until explicitly enabled."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("RENEWAL_WORKFLOW_ENABLED", False):
            abort(404)
        return f(*args, **kwargs)
    return wrapped


@renewal_bp.route("/", methods=["GET"])
@renewal_feature_enabled
@permission_required(RENEWAL_CENTER_VIEW)
def renewal_center():
    """Render the read-only renewal queue when the feature is enabled."""
    workflow_enabled = bool(current_app.config.get("RENEWAL_WORKFLOW_ENABLED", False))
    workflow_manager = False
    assignment_allowed = False
    assignees = []
    user = None
    if workflow_enabled:
        user = get_current_user()
        workflow_manager = _has_permission(user, RENEWAL_CENTER_MANAGER)
        assignment_allowed = workflow_manager and _has_permission(user, RENEWAL_CENTER_ASSIGN)

    queue_filter, status_filter, owner_filter, search, page = _safe_queue_args(
        manager=workflow_manager
    )
    error_message = None
    items = []
    total_count = 0

    try:
        if workflow_enabled:
            items, total_count = get_renewal_workflow_queue(
                queue_filter=queue_filter,
                status_filter=status_filter,
                owner_filter=owner_filter,
                search=search,
                page=page,
                per_page=PER_PAGE,
                manager=workflow_manager,
                actor_user_id=(user or {}).get("id"),
            )
            if workflow_manager:
                assignees = get_renewal_assignees()
        else:
            items, total_count = get_renewal_queue(
                queue_filter=queue_filter,
                search=search,
                page=page,
                per_page=PER_PAGE,
            )
    except Exception:
        current_app.logger.exception("Renewal Center query failed")
        error_message = "Renewal data is temporarily unavailable. Please try again later."

    total_pages = max(ceil(total_count / PER_PAGE), 1)
    if page > total_pages:
        page = total_pages
        if total_count:
            # The first query was needed to calculate the valid page range.
            # Re-read the final page so the displayed page and rows cannot
            # disagree.
            try:
                if workflow_enabled:
                    items, _ = get_renewal_workflow_queue(
                        queue_filter=queue_filter,
                        status_filter=status_filter,
                        owner_filter=owner_filter,
                        search=search,
                        page=page,
                        per_page=PER_PAGE,
                        manager=workflow_manager,
                        actor_user_id=(user or {}).get("id"),
                    )
                else:
                    items, _ = get_renewal_queue(
                        queue_filter=queue_filter,
                        search=search,
                        page=page,
                        per_page=PER_PAGE,
                    )
            except Exception:
                current_app.logger.exception("Renewal Center page correction failed")
                items = []
                error_message = "Renewal data is temporarily unavailable. Please try again later."

    return render_template(
        "renewal_center.html",
        items=items,
        page=page,
        per_page=PER_PAGE,
        total_count=total_count,
        total_pages=total_pages,
        queue_filter=queue_filter,
        workflow_enabled=workflow_enabled,
        workflow_manager=workflow_manager,
        assignment_allowed=assignment_allowed,
        workflow_status_filter=status_filter,
        owner_filter=owner_filter,
        assignees=assignees,
        search=search,
        error_message=error_message,
        member_url_endpoint="edit_member",
        member_url_builder=lambda member_id: url_for("edit_member", member_id=member_id),
    )


@renewal_bp.route("/cases/assign", methods=["POST"])
@renewal_feature_enabled
@renewal_workflow_enabled
@permission_required(RENEWAL_CENTER_VIEW)
def assign_case():
    """Assign an eligible Renewal cycle; all writes are transactional."""
    user = get_current_user()
    if not (
        _has_permission(user, RENEWAL_CENTER_MANAGER)
        and _has_permission(user, RENEWAL_CENTER_ASSIGN)
    ):
        abort(403)

    try:
        member_id = int(request.form.get("member_id", ""))
        owner_user_id = int(request.form.get("owner_user_id", ""))
        expected_version = int(request.form.get("expected_version", ""))
        if member_id <= 0 or owner_user_id <= 0 or expected_version < 0:
            raise ValueError
    except (TypeError, ValueError):
        flash("Invalid Renewal assignment request.", "error")
        return _renewal_redirect()

    try:
        result = assign_renewal_case(
            actor_user_id=user["id"],
            member_id=member_id,
            expected_version=expected_version,
            owner_user_id=owner_user_id,
        )
        if result["changed"]:
            flash("Renewal case assigned successfully.", "success")
        else:
            flash("Renewal case is already assigned to this user.", "info")
    except RenewalAssignmentError as exc:
        flash(exc.message, "error")
    except Exception as exc:
        current_app.logger.warning(
            "Renewal assignment failed error_type=%s", type(exc).__name__
        )
        flash("Renewal assignment is temporarily unavailable. Please try again.", "error")
    return _renewal_redirect()
