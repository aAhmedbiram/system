from flask import Blueprint, jsonify, request, render_template
from system_app.crm.permissions import (
    login_required, crm_permission_required, get_current_user,
    CRM_VIEW, CRM_CREATE, CRM_EDIT, CRM_ASSIGN, CRM_UPDATE_STAGE, CRM_CONVERT,
    CRM_BULK_LEADS
)
from system_app.crm import services
from system_app.crm.services import CRMConflictError, CRMForbiddenError, CRMNotFoundError, CRMProtectedFieldError, CRMValidationError

crm_routes = Blueprint('crm_routes', __name__)

@crm_routes.route('/')
@login_required
@crm_permission_required(CRM_VIEW)
def crm_home():
    """CRM Root Dashboard Page."""
    from system_app.app import get_common_template_context
    common_context = get_common_template_context()
    return render_template("crm_dashboard.html", **common_context)

@crm_routes.route('/summary')
@login_required
@crm_permission_required(CRM_VIEW)
def crm_summary_json():
    """CRM JSON summary endpoint for legacy compatibility or UI fetch."""
    summary = services.get_crm_home_summary()
    return jsonify(summary)

@crm_routes.route('/health')
@login_required
@crm_permission_required(CRM_VIEW)
def crm_health_endpoint():
    """CRM Health Check Endpoint."""
    health = services.get_crm_health()
    return jsonify(health)

@crm_routes.route('/leads', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def list_leads_route():
    """Gets paginated and filtered list of leads."""
    current_user = get_current_user()
    page = request.args.get('page')
    per_page = request.args.get('per_page')

    filters = {
        'stage': request.args.get('stage'),
        'source': request.args.get('source'),
        'member_status': request.args.get('member_status'),
        'search': request.args.get('search'),
        'assigned_user_id': request.args.get('assigned_user_id')
    }

    try:
        leads_list = services.list_leads(current_user, page, per_page, filters)
        return jsonify(leads_list), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/filter-users', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def list_dashboard_filter_users_route():
    """Returns minimal eligible CRM users for read-only dashboard filters."""
    users_list = services.list_filter_users(get_current_user())
    return jsonify(users_list), 200

@crm_routes.route('/leads', methods=['POST'])
@login_required
@crm_permission_required(CRM_CREATE)
def create_lead_route():
    """Creates a new prospect or linked-member lead."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}

    try:
        lead_id = services.create_lead(current_user, data)
        return jsonify({"id": lead_id, "status": "created"}), 201
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/bulk', methods=['GET'])
@login_required
@crm_permission_required(CRM_BULK_LEADS)
def bulk_leads_route():
    """Renders the bulk lead creation workspace."""
    from system_app.app import get_common_template_context
    current_user = get_current_user()
    common_context = get_common_template_context()
    preview_token = request.args.get('preview_token', '').strip()
    preview_summary = None
    preview_error = None
    bulk_state = None

    if preview_token:
        try:
            operation_state = services.get_bulk_preview_operation_state(preview_token, current_user)
            preview_snapshot = operation_state.get('snapshot') or {}
            distribution_mode = (preview_snapshot.get('distribution') or {}).get('mode')
            preview_summary = {
                "source": preview_snapshot.get('source'),
                "selected_count": preview_snapshot.get('selected_count', 0),
                "eligible_count": preview_snapshot.get('eligible_count', 0),
                "skipped_count": preview_snapshot.get('skipped_count', 0),
                "missing_count": preview_snapshot.get('missing_count', 0),
                "assignment_plan_count": len(preview_snapshot.get('assignment_plan') or []),
                "distribution": preview_snapshot.get('assignable_users', []) if distribution_mode == 'equal' else [],
                "distribution_mode": distribution_mode,
                "preview_token": preview_token,
                "status": operation_state.get('status')
            }
            bulk_state = {
                "preview_token": preview_token,
                "status": operation_state.get('status'),
                "snapshot": preview_snapshot,
                "execution": operation_state.get('execution'),
                "summary": preview_summary
            }
        except (CRMForbiddenError, CRMNotFoundError) as e:
            preview_error = str(e)

    return render_template(
        "crm_bulk_leads.html",
        preview_token=preview_token,
        preview_summary=preview_summary,
        bulk_state=bulk_state,
        preview_error=preview_error,
        **common_context
    )

@crm_routes.route('/leads/bulk/members', methods=['GET'])
@login_required
@crm_permission_required(CRM_BULK_LEADS)
def bulk_leads_members_route():
    """Returns paginated CRM members for the bulk selection workspace."""
    current_user = get_current_user()
    page = request.args.get('page')
    per_page = request.args.get('per_page')
    allowed_filter_keys = [
        'view',
        'expires_within',
        'expires_month',
        'expires_year',
        'search_id',
        'search_name',
        'search_national_id',
        'search_phone',
        'search_age',
        'search_gender',
        'search_actual_start',
        'search_start_date',
        'search_end_date',
        'search_package',
        'search_fees',
        'search_invitations',
        'search_comment'
    ]
    filters = {}
    for key in allowed_filter_keys:
        value = request.args.get(key)
        if value is not None and str(value).strip() != "":
            filters[key] = value

    try:
        listing = services.list_bulk_members(current_user, page, per_page, filters)
        return jsonify(listing), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/leads/bulk/invitations', methods=['GET'])
@login_required
@crm_permission_required(CRM_BULK_LEADS)
def bulk_leads_invitations_route():
    """Returns paginated invitation-friend candidates for recurring CRM intake."""
    current_user = get_current_user()
    page = request.args.get('page')
    per_page = request.args.get('per_page')
    allowed_filter_keys = [
        'search_name',
        'search_phone',
        'used_by',
        'invitation_month',
        'invitation_year'
    ]
    filters = {}
    for key in allowed_filter_keys:
        value = request.args.get(key)
        if value is not None and str(value).strip() != "":
            filters[key] = value

    try:
        listing = services.list_invitation_candidates(current_user, page, per_page, filters)
        return jsonify(listing), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/leads/bulk/preview', methods=['POST'])
@login_required
@crm_permission_required(CRM_BULK_LEADS)
def bulk_leads_preview_route():
    """Returns an authoritative bulk selection preview without creating records."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        preview = services.preview_bulk_member_leads(current_user, data)
        return jsonify(preview), 200
    except CRMValidationError as e:
        payload = {"error": e.error_code, "message": str(e)}
        if e.details:
            payload["details"] = e.details
        return jsonify(payload), 400
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/bulk/execute', methods=['POST'])
@login_required
@crm_permission_required(CRM_BULK_LEADS)
def bulk_leads_execute_route():
    """Executes a previously approved bulk member preview."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    preview_token = data.get('preview_token')
    try:
        result = services.execute_bulk_member_leads(current_user, preview_token)
        return jsonify(result), 200
    except CRMValidationError as e:
        payload = {"error": e.error_code, "message": str(e)}
        if e.details:
            payload["details"] = e.details
        return jsonify(payload), 400
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/<int:lead_id>', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def get_lead_route(lead_id):
    """Retrieves detailed lead parameters."""
    current_user = get_current_user()
    try:
        lead = services.get_lead(current_user, lead_id)
        return jsonify(lead), 200
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403

@crm_routes.route('/leads/<int:lead_id>/view', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def view_lead_route(lead_id):
    """Renders the HTML Lead Details page shell."""
    from system_app.app import get_common_template_context
    common_context = get_common_template_context()
    return render_template("crm_lead_detail.html", lead_id=lead_id, **common_context)

@crm_routes.route('/leads/<int:lead_id>', methods=['PATCH'])
@login_required
@crm_permission_required(CRM_EDIT)
def update_lead_route(lead_id):
    """Updates permitted whitelist fields on lead."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        services.update_lead(current_user, lead_id, data)
        return jsonify({"status": "updated"}), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMProtectedFieldError as e:
        return jsonify({
            "error": "protected_field",
            "message": str(e),
            "fields": e.fields
        }), 400
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403

@crm_routes.route('/leads/<int:lead_id>/archive', methods=['POST'])
@login_required
@crm_permission_required(CRM_EDIT)
def archive_lead_route(lead_id):
    """Soft-archives a CRM lead."""
    current_user = get_current_user()
    try:
        services.archive_lead(current_user, lead_id)
        return jsonify({"status": "archived"}), 200
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403

@crm_routes.route('/members/search', methods=['GET'])
@login_required
@crm_permission_required(CRM_CREATE)
def search_members_route():
    """Endpoint for finding existing gym members to link to leads."""
    current_user = get_current_user()
    q = request.args.get('q', '')
    try:
        results = services.search_existing_members(current_user, q)
        return jsonify(results), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/users', methods=['GET'])
@login_required
@crm_permission_required(CRM_ASSIGN)
def list_assignable_users_route():
    """Returns a list of approved users that can receive lead assignments."""
    current_user = get_current_user()
    users_list = services.list_assignable_users(current_user)
    return jsonify(users_list), 200

@crm_routes.route('/leads/<int:lead_id>/assign', methods=['POST'])
@login_required
@crm_permission_required(CRM_ASSIGN)
def assign_lead_route(lead_id):
    """Assigns or reassigns a single lead to a user."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    target_user_id = data.get('user_id')

    if target_user_id is None:
        return jsonify({"error": "invalid_input", "message": "'user_id' is required"}), 400

    try:
        services.assign_lead(current_user, lead_id, target_user_id)
        return jsonify({"status": "assigned", "lead_id": lead_id, "assigned_to": target_user_id}), 200
    except CRMNotFoundError as e:
        return jsonify({"error": e.error_code if hasattr(e, 'error_code') else "not_found", "message": str(e)}), 404
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/leads/<int:lead_id>/unassign', methods=['POST'])
@login_required
@crm_permission_required(CRM_ASSIGN)
def unassign_lead_route(lead_id):
    """Unassigns a lead, clearing the assignee."""
    current_user = get_current_user()
    try:
        services.unassign_lead(current_user, lead_id)
        return jsonify({"status": "unassigned", "lead_id": lead_id}), 200
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/bulk-assign', methods=['POST'])
@login_required
@crm_permission_required(CRM_ASSIGN)
def bulk_assign_leads_route():
    """Bulk assigns multiple leads to a user."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    lead_ids = data.get('lead_ids')
    target_user_id = data.get('user_id')

    if target_user_id is None:
        return jsonify({"error": "invalid_input", "message": "'user_id' is required"}), 400

    try:
        services.bulk_assign_leads(current_user, lead_ids, target_user_id)
        return jsonify({"status": "bulk_assigned", "count": len(lead_ids)}), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMNotFoundError as e:
        return jsonify({"error": e.error_code if hasattr(e, 'error_code') else "not_found", "message": str(e)}), 404
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/<int:lead_id>/activities', methods=['POST'])
@login_required
@crm_permission_required(CRM_EDIT)
def create_activity_route(lead_id):
    """Creates a new activity entry and updates lead follow-ups."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        services.add_activity(current_user, lead_id, data)
        return jsonify({"status": "created"}), 201
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/<int:lead_id>/activities', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def list_activities_route(lead_id):
    """Retrieves lead activity log timeline."""
    current_user = get_current_user()
    page = request.args.get('page')
    per_page = request.args.get('per_page')
    try:
        timeline = services.list_activities(current_user, lead_id, page, per_page)
        return jsonify(timeline), 200
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403

@crm_routes.route('/follow-ups', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def list_follow_ups_route():
    """Lists pending follow-up leads for the user or organization."""
    current_user = get_current_user()
    page = request.args.get('page')
    per_page = request.args.get('per_page')
    filters = {
        'status': request.args.get('status')
    }
    try:
        follow_ups = services.list_follow_ups(current_user, page, per_page, filters)
        return jsonify(follow_ups), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400

@crm_routes.route('/follow-ups/view', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def view_follow_ups_route():
    """Renders the operational follow-up queue page."""
    from system_app.app import get_common_template_context
    common_context = get_common_template_context()
    initial_status = request.args.get('status', '')
    return render_template("crm_follow_up_queue.html", initial_status=initial_status, **common_context)

@crm_routes.route('/leads/<int:lead_id>/stage', methods=['POST'])
@login_required
@crm_permission_required(CRM_UPDATE_STAGE)
def change_lead_stage_route(lead_id):
    """Updates lead stage with pipeline rules."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        res = services.change_lead_stage(current_user, lead_id, data)
        return jsonify(res), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/<int:lead_id>/reopen', methods=['POST'])
@login_required
@crm_permission_required(CRM_UPDATE_STAGE)
def reopen_lead_route(lead_id):
    """Reopens a LOST lead."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        res = services.reopen_lead(current_user, lead_id, data)
        return jsonify(res), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/pipeline', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def get_pipeline_summary_route():
    """Retrieves lead counts grouped by stage."""
    current_user = get_current_user()
    summary = services.get_pipeline_summary(current_user)
    return jsonify(summary), 200

@crm_routes.route('/leads/<int:lead_id>/convert', methods=['POST'])
@login_required
@crm_permission_required(CRM_CONVERT)
def convert_lead_route(lead_id):
    """Converts a lead into a gym member or reactivates an existing member."""
    current_user = get_current_user()
    data = request.get_json(silent=True) or {}
    try:
        res = services.convert_lead(current_user, lead_id, data)
        return jsonify(res), 200
    except ValueError as e:
        return jsonify({"error": "invalid_input", "message": str(e)}), 400
    except CRMNotFoundError as e:
        return jsonify({"error": "not_found", "message": str(e)}), 404
    except CRMForbiddenError as e:
        return jsonify({"error": "forbidden", "message": str(e)}), 403
    except CRMConflictError as e:
        return jsonify({"error": e.error_code, "message": str(e), "details": e.details}), 409

@crm_routes.route('/leads/<int:lead_id>/convert/view', methods=['GET'])
@login_required
@crm_permission_required(CRM_CONVERT)
def view_convert_lead_route(lead_id):
    """Renders the conversion / reactivation workspace."""
    from system_app.app import get_common_template_context
    common_context = get_common_template_context()
    return render_template("crm_lead_convert.html", lead_id=lead_id, **common_context)

@crm_routes.route('/follow-ups/summary', methods=['GET'])
@login_required
@crm_permission_required(CRM_VIEW)
def get_follow_ups_summary_route():
    """Gets follow-up counts for overdue, today, and upcoming."""
    current_user = get_current_user()
    summary = services.get_follow_up_summary(current_user)
    return jsonify(summary), 200
