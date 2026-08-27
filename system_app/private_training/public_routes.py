from __future__ import annotations

from flask import Blueprint, flash, make_response, redirect, render_template, request, url_for

from .queries import get_private_training_pending_session
from .services import (
    PrivateTrainingAlreadyProcessedError,
    PrivateTrainingCancelledError,
    PrivateTrainingCompletedError,
    PrivateTrainingExpiredError,
    PrivateTrainingForbiddenError,
    PrivateTrainingNotFoundError,
    PrivateTrainingError,
    list_private_training_sessions,
    resolve_portal_token,
    approve_private_training_session,
)

private_training_public_bp = Blueprint("private_training_public", __name__)


def _portal_privacy_headers(response):
    response.headers["Cache-Control"] = "no-store, private"
    response.headers["Pragma"] = "no-cache"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


@private_training_public_bp.after_request
def _apply_portal_privacy_headers(response):
    if request and request.path.startswith("/private-training/member/"):
        return _portal_privacy_headers(response)
    return response


def _not_found_response():
    response = make_response(
        render_template(
            "error.html",
            error_code=404,
            error_message="The page you're looking for doesn't exist.",
        ),
        404,
    )
    return _portal_privacy_headers(response)


def _gone_response():
    response = make_response(
        render_template(
            "private_training/member_portal.html",
            portal_ended=True,
            portal_ended_message="This private training subscription is no longer available.",
        ),
        410,
    )
    return _portal_privacy_headers(response)


def _resolve_portal(raw_token: str):
    try:
        return resolve_portal_token(raw_token), None
    except (PrivateTrainingCancelledError, PrivateTrainingCompletedError, PrivateTrainingExpiredError):
        return None, _gone_response()
    except PrivateTrainingNotFoundError:
        return None, _not_found_response()


def _portal_context(raw_token: str, resolved: dict):
    subscription = resolved["subscription"]
    all_sessions = list_private_training_sessions(subscription["id"])
    sessions = [session for session in all_sessions if session.get("status") != "REJECTED"]
    pending_session = get_private_training_pending_session(subscription["id"])
    return {
        "raw_token": raw_token,
        "subscription": subscription,
        "pending_session": pending_session,
        "sessions": sessions,
        "portal_ended": False,
        "portal_ended_message": None,
        "approve_url": url_for("private_training_public.member_portal_approve", raw_token=raw_token, session_id=pending_session["id"]) if pending_session else None,
    }


def _portal_render(raw_token: str, resolved: dict):
    context = _portal_context(raw_token, resolved)
    response = make_response(render_template("private_training/member_portal.html", **context), 200)
    return _portal_privacy_headers(response)


@private_training_public_bp.route("/member/<raw_token>", methods=["GET"])
def member_portal(raw_token: str):
    resolved, response = _resolve_portal(raw_token)
    if response:
        return response
    return _portal_render(raw_token, resolved)


@private_training_public_bp.route("/member/<raw_token>/sessions/<int:session_id>/approve", methods=["POST"])
def member_portal_approve(raw_token: str, session_id: int):
    resolved, response = _resolve_portal(raw_token)
    if response:
        return response

    subscription = resolved["subscription"]
    portal_context = {"subscription_id": subscription["id"]}

    try:
        result = approve_private_training_session(subscription["id"], session_id, portal_context)
        flash("Session approved successfully.", "success")
        if result.get("outcome") == "already_approved":
            flash("This session was already approved.", "info")
        return redirect(url_for("private_training_public.member_portal", raw_token=raw_token))
    except PrivateTrainingAlreadyProcessedError:
        flash("This session was already processed.", "error")
        return redirect(url_for("private_training_public.member_portal", raw_token=raw_token))
    except (PrivateTrainingForbiddenError, PrivateTrainingNotFoundError):
        return _not_found_response()
    except (PrivateTrainingCancelledError, PrivateTrainingCompletedError, PrivateTrainingExpiredError):
        return _gone_response()
    except PrivateTrainingError as exc:
        flash(str(exc), "error")
        return _portal_render(raw_token, resolved), 400
