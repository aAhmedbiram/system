-- Migration: Add CRM bulk lead operations table
-- Date: 2026-08-17

CREATE TABLE IF NOT EXISTS crm_bulk_lead_operations (
    id SERIAL PRIMARY KEY,
    token VARCHAR(128) NOT NULL UNIQUE,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'PREVIEW',
    snapshot JSONB NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    started_at TIMESTAMP WITH TIME ZONE NULL,
    completed_at TIMESTAMP WITH TIME ZONE NULL,
    CONSTRAINT chk_crm_bulk_lead_operations_status CHECK (status IN ('PREVIEW', 'EXECUTING', 'COMPLETED', 'FAILED'))
);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_lead_operations_created_by
    ON crm_bulk_lead_operations(created_by_user_id);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_lead_operations_status
    ON crm_bulk_lead_operations(status);

CREATE INDEX IF NOT EXISTS idx_crm_bulk_lead_operations_expires_at
    ON crm_bulk_lead_operations(expires_at);
