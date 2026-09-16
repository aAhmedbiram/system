-- Additive schema for the private-training Check-In + portal invitation workflow.
-- Apply only after reviewing the existing private-training tables. This file is
-- intentionally not run by application startup or by this change.

ALTER TABLE private_training_portal_tokens
    ADD COLUMN IF NOT EXISTS session_id INTEGER NULL
    REFERENCES private_training_sessions(id) ON DELETE RESTRICT;

CREATE INDEX IF NOT EXISTS idx_private_training_portal_tokens_session_active
    ON private_training_portal_tokens(session_id)
    WHERE session_id IS NOT NULL AND revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS private_training_checkin_operations (
    client_operation_id UUID PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
    session_id INTEGER NULL REFERENCES private_training_sessions(id) ON DELETE RESTRICT,
    portal_token_id INTEGER NULL REFERENCES private_training_portal_tokens(id) ON DELETE RESTRICT,
    status VARCHAR(24) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_private_training_checkin_operations_status
        CHECK (status IN ('PROCESSING', 'COMPLETED')),
    CONSTRAINT chk_private_training_checkin_operations_references
        CHECK (
            (status = 'PROCESSING' AND session_id IS NULL AND portal_token_id IS NULL)
            OR (status = 'COMPLETED' AND session_id IS NOT NULL AND portal_token_id IS NOT NULL)
        )
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'chk_private_training_checkin_operations_references'
    ) THEN
        ALTER TABLE private_training_checkin_operations
        ADD CONSTRAINT chk_private_training_checkin_operations_references
        CHECK (
            (status = 'PROCESSING' AND session_id IS NULL AND portal_token_id IS NULL)
            OR (status = 'COMPLETED' AND session_id IS NOT NULL AND portal_token_id IS NOT NULL)
        );
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_private_training_checkin_operations_user
    ON private_training_checkin_operations(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_private_training_checkin_operations_subscription
    ON private_training_checkin_operations(subscription_id, created_at DESC);
