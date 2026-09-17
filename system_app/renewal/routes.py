"""HTTP boundary for the read-only Renewal Command Center."""

from __future__ import annotations

from functools import wraps
from math import ceil

from flask import Blueprint, abort, current_app, render_template, request, url_for

from system_app.app import permission_required
from system_app.renewal.queries import RENEWAL_FILTERS, get_renewal_queue

renewal_bp = Blueprint("renewal", __name__)

RENEWAL_CENTER_VIEW = "renewal_center_view"
PER_PAGE = 25


def renewal_feature_enabled(f):
    """Hide the entire Renewal Center boundary while the feature is disabled."""
    @wraps(f)
    def wrapped(*args, **kwargs):
        if not current_app.config.get("RENEWAL_COMMAND_CENTER_ENABLED", False):
            abort(404)
        return f(*args, **kwargs)
    return wrapped


@renewal_bp.route("/", methods=["GET"])
@renewal_feature_enabled
@permission_required(RENEWAL_CENTER_VIEW)
def renewal_center():
    """Render the read-only renewal queue when the feature is enabled."""
    page = request.args.get("page", 1, type=int)
    page = max(page or 1, 1)
    queue_filter = request.args.get("filter", "all", type=str).strip().lower()
    if queue_filter not in RENEWAL_FILTERS:
        queue_filter = "all"
    search = request.args.get("search", "", type=str).strip()
    error_message = None
    items = []
    total_count = 0

    try:
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
        search=search,
        error_message=error_message,
        member_url_endpoint="edit_member",
        member_url_builder=lambda member_id: url_for("edit_member", member_id=member_id),
    )
