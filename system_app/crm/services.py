from system_app.crm.queries import crm_schema_health_check, get_crm_counts

def get_crm_health():
    """Runs a health check on all CRM tables and returns module operational status."""
    table_health = crm_schema_health_check()
    all_ok = all(table_health.values())

    return {
        "status": "ok" if all_ok else "degraded",
        "module": "crm",
        "tables": table_health
    }

def get_crm_home_summary():
    """Returns static summary attributes for the root placeholder response."""
    db_counts = get_crm_counts()
    return {
        "module": "crm",
        "status": "ready",
        "phase": "1B",
        "database_metrics": db_counts
    }
