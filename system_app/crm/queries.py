from system_app.queries import query_db

def get_crm_counts():
    """Returns basic counts of leads, activities, and campaigns to prove DB reachability."""
    try:
        leads_count = query_db("SELECT COUNT(*) as count FROM crm_leads", one=True)
        activities_count = query_db("SELECT COUNT(*) as count FROM crm_activities", one=True)
        campaigns_count = query_db("SELECT COUNT(*) as count FROM crm_campaigns", one=True)

        return {
            "leads": leads_count["count"] if leads_count else 0,
            "activities": activities_count["count"] if activities_count else 0,
            "campaigns": campaigns_count["count"] if campaigns_count else 0
        }
    except Exception as e:
        print(f"Error checking CRM counts: {e}")
        return None

def crm_schema_health_check():
    """Validates if all three CRM tables exist and can be queried."""
    health = {}
    for table in ["crm_campaigns", "crm_leads", "crm_activities"]:
        try:
            query_db(f"SELECT 1 FROM {table} LIMIT 1")
            health[table] = True
        except Exception:
            health[table] = False
    return health
