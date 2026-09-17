from pathlib import Path

from system_app.renewal.permissions import (
    RENEWAL_CENTER_ASSIGN,
    RENEWAL_CENTER_FOLLOW_UP,
    RENEWAL_CENTER_MANAGER,
    RENEWAL_CENTER_VIEW,
    RENEWAL_PERMISSIONS,
)


ROOT = Path(__file__).parent
MIGRATION = ROOT / "system_app/migrations/add_renewal_workflow.sql"


def test_renewal_workflow_flag_is_false_by_default_and_phase1a_flag_is_separate():
    source = (ROOT / "system_app/app.py").read_text(encoding="utf-8")
    assert "RENEWAL_WORKFLOW_ENABLED" in source
    assert "os.environ.get('RENEWAL_WORKFLOW_ENABLED', '').strip().lower()" in source
    assert "RENEWAL_COMMAND_CENTER_ENABLED" in source
    assert "RENEWAL_WORKFLOW_ENABLED'] = (" in source
    assert "in {'1', 'true', 'yes', 'on'}" in source


def test_renewal_permissions_are_explicit_and_crm_independent():
    keys = {key for key, _label in RENEWAL_PERMISSIONS}
    assert keys == {
        RENEWAL_CENTER_VIEW,
        RENEWAL_CENTER_FOLLOW_UP,
        RENEWAL_CENTER_ASSIGN,
        RENEWAL_CENTER_MANAGER,
    }
    assert not any(key.startswith("crm_") for key in keys)

    app_source = (ROOT / "system_app/app.py").read_text(encoding="utf-8")
    assert "from system_app.renewal.permissions import RENEWAL_PERMISSIONS" in app_source
    assert "renewal_permissions = list(RENEWAL_PERMISSIONS)" in app_source
    assert "all_permissions = general_permissions + crm_permissions + renewal_permissions" in app_source


def test_user_permission_template_has_a_separate_renewal_group():
    template = (ROOT / "system_app/templates/user_permissions.html").read_text(encoding="utf-8")
    assert 'colspan="{{ renewal_permissions|length }}">Renewal</th>' in template
    assert "{% for key, label in renewal_permissions %}" in template


def test_migration_is_additive_and_has_only_phase1b_objects():
    sql = MIGRATION.read_text(encoding="utf-8")
    lowered = sql.lower()
    assert "create table if not exists renewal_cases" in lowered
    assert "create table if not exists renewal_follow_ups" in lowered
    assert "create table if not exists renewal_assignment_events" in lowered
    assert "drop " not in lowered
    assert "crm_leads" not in lowered
    assert "crm_activities" not in lowered
    assert "backfill" in lowered
    assert "renewal_logs" not in lowered
    assert "phone" not in lowered
    assert "whatsapp" not in lowered
    assert "token" not in lowered
    assert "client_operation_id uuid not null" in lowered
    assert "unique (member_id, cycle_end_date)" in lowered
    assert "follow_up_due" not in lowered
    assert "renewed" not in lowered
    assert "lost" not in lowered


def test_migration_constraints_and_planned_indexes_are_declared():
    sql = MIGRATION.read_text(encoding="utf-8").lower()
    for fragment in (
        "references members(id) on delete restrict",
        "references users(id) on delete set null",
        "check (version >= 1)",
        "'unassigned', 'open', 'waiting', 'paused'",
        "'call', 'visit', 'other'",
        "'no_answer', 'reached', 'call_back'",
        "idx_renewal_cases_owner_status_cycle",
        "idx_renewal_cases_status_next_follow_up_cycle",
        "idx_renewal_follow_ups_case_created",
        "idx_renewal_assignment_events_case_created",
    ):
        assert fragment in sql


def test_migration_runner_registers_the_new_migration_without_startup_execution():
    runner = (ROOT / "system_app/migrations/run_migrations.py").read_text(encoding="utf-8")
    assert "run_migration('add_renewal_workflow.sql')" in runner
    assert "add_renewal_workflow.sql" not in (ROOT / "system_app/app.py").read_text(encoding="utf-8")
