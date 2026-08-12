-- Migration: Add CRM Phase 1A Tables
-- Date: 2026-08-12

-- 1. Create crm_campaigns table
CREATE TABLE IF NOT EXISTS crm_campaigns (
    id SERIAL PRIMARY KEY,
    name VARCHAR(255) NOT NULL,
    description TEXT NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE
);

-- 2. Create crm_leads table
CREATE TABLE IF NOT EXISTS crm_leads (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NULL REFERENCES members(id) ON DELETE SET NULL,
    name VARCHAR(255) NOT NULL,
    phone VARCHAR(50) NOT NULL,
    email VARCHAR(255) NULL,
    source VARCHAR(50) NOT NULL,
    stage VARCHAR(50) NOT NULL DEFAULT 'NEW',
    assigned_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    assigned_at TIMESTAMP WITH TIME ZONE NULL,
    campaign_id INTEGER NULL REFERENCES crm_campaigns(id) ON DELETE SET NULL,
    next_follow_up_at TIMESTAMP WITH TIME ZONE NULL,
    lost_reason VARCHAR(100) NULL,
    notes TEXT NULL,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    converted_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    converted_at TIMESTAMP WITH TIME ZONE NULL,
    is_archived BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT chk_crm_leads_stage CHECK (stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL', 'WON', 'LOST'))
);

-- 3. Create crm_activities table
CREATE TABLE IF NOT EXISTS crm_activities (
    id SERIAL PRIMARY KEY,
    lead_id INTEGER NOT NULL REFERENCES crm_leads(id) ON DELETE RESTRICT,
    user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    user_username_snapshot VARCHAR(255) NULL,
    activity_type VARCHAR(50) NOT NULL,
    note TEXT NULL,
    result TEXT NULL,
    old_stage VARCHAR(50) NULL,
    new_stage VARCHAR(50) NULL,
    old_assigned_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    new_assigned_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    follow_up_at TIMESTAMP WITH TIME ZONE NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_crm_activities_type CHECK (activity_type IN ('CALL', 'WHATSAPP', 'VISIT', 'NOTE', 'FOLLOW_UP', 'STAGE_CHANGE', 'ASSIGNED', 'REASSIGNED', 'CONVERTED', 'REACTIVATED', 'LOST', 'REOPENED'))
);

-- 4. Create Indexes
CREATE INDEX IF NOT EXISTS idx_crm_leads_member_id ON crm_leads(member_id);
CREATE INDEX IF NOT EXISTS idx_crm_leads_assigned_user ON crm_leads(assigned_user_id);
CREATE INDEX IF NOT EXISTS idx_crm_leads_stage ON crm_leads(stage);
CREATE INDEX IF NOT EXISTS idx_crm_leads_next_follow_up ON crm_leads(next_follow_up_at);
CREATE INDEX IF NOT EXISTS idx_crm_leads_campaign ON crm_leads(campaign_id);
CREATE INDEX IF NOT EXISTS idx_crm_leads_created_at ON crm_leads(created_at);

CREATE INDEX IF NOT EXISTS idx_crm_activities_lead_id ON crm_activities(lead_id);
CREATE INDEX IF NOT EXISTS idx_crm_activities_created_at ON crm_activities(created_at);
CREATE INDEX IF NOT EXISTS idx_crm_activities_user_id ON crm_activities(user_id);

-- 5. Partial Unique Index for Active Leads
CREATE UNIQUE INDEX IF NOT EXISTS idx_unique_active_member_lead
ON crm_leads(member_id)
WHERE member_id IS NOT NULL
  AND stage IN ('NEW', 'CONTACTED', 'FOLLOW_UP', 'INTERESTED', 'TRIAL')
  AND is_archived = FALSE;
