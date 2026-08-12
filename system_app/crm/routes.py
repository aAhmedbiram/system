from flask import Blueprint, jsonify
from system_app.crm.permissions import login_required, crm_permission_required, CRM_VIEW
from system_app.crm.services import get_crm_health, get_crm_home_summary

crm_routes = Blueprint('crm_routes', __name__)

@crm_routes.route('/')
@login_required
@crm_permission_required(CRM_VIEW)
def crm_home():
    """CRM Root Placeholder Endpoint."""
    summary = get_crm_home_summary()
    return jsonify(summary)

@crm_routes.route('/health')
@login_required
@crm_permission_required(CRM_VIEW)
def crm_health_endpoint():
    """CRM Health Check Endpoint."""
    health = get_crm_health()
    return jsonify(health)
