-- Private Training domain migration
-- Phase 1A foundation only

CREATE TABLE IF NOT EXISTS private_training_subscriptions (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL REFERENCES members(id) ON DELETE RESTRICT,
    trainer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    total_sessions INTEGER NOT NULL,
    private_start_date DATE NOT NULL,
    private_expiry_date DATE NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'ASSIGNED',
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_private_training_subscriptions_total_sessions CHECK (total_sessions > 0),
    CONSTRAINT chk_private_training_subscriptions_dates CHECK (private_expiry_date >= private_start_date),
    CONSTRAINT chk_private_training_subscriptions_status CHECK (status IN ('ASSIGNED', 'ACTIVE', 'COMPLETED', 'EXPIRED', 'CANCELLED'))
);

CREATE TABLE IF NOT EXISTS private_training_sessions (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
    trainer_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
    checked_in_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(40) NOT NULL,
    approved_at TIMESTAMPTZ NULL,
    rejected_at TIMESTAMPTZ NULL,
    rejection_reason TEXT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT chk_private_training_sessions_status CHECK (status IN ('PENDING_MEMBER_APPROVAL', 'APPROVED', 'REJECTED')),
    CONSTRAINT chk_private_training_sessions_rejection_reason CHECK (
        status <> 'REJECTED' OR length(btrim(COALESCE(rejection_reason, ''))) > 0
    )
);

CREATE TABLE IF NOT EXISTS private_training_portal_tokens (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
    token_hash CHAR(64) NOT NULL UNIQUE,
    created_by_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMPTZ NULL,
    last_used_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_trainer_status_start
    ON private_training_subscriptions(trainer_user_id, status, private_start_date);

CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_member_status
    ON private_training_subscriptions(member_id, status);

CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_expiry_date
    ON private_training_subscriptions(private_expiry_date);

CREATE INDEX IF NOT EXISTS idx_private_training_sessions_subscription_status_checked_in
    ON private_training_sessions(subscription_id, status, checked_in_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_private_training_sessions_one_pending_per_subscription
    ON private_training_sessions(subscription_id)
    WHERE status = 'PENDING_MEMBER_APPROVAL';

CREATE INDEX IF NOT EXISTS idx_private_training_sessions_trainer_checked_in
    ON private_training_sessions(trainer_user_id, checked_in_at DESC);

CREATE INDEX IF NOT EXISTS idx_private_training_portal_tokens_created_by
    ON private_training_portal_tokens(created_by_user_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_private_training_portal_tokens_active_per_subscription
    ON private_training_portal_tokens(subscription_id)
    WHERE revoked_at IS NULL;
