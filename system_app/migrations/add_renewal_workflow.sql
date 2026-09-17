-- Additive schema for Renewal Command Center Phase 1B.1.
-- This migration creates no cases and performs no member/CRM backfill.

CREATE TABLE IF NOT EXISTS renewal_cases (
    id SERIAL PRIMARY KEY,
    member_id INTEGER NOT NULL
        REFERENCES members(id) ON DELETE RESTRICT,
    cycle_end_date DATE NOT NULL,
    owner_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL,
    operational_status VARCHAR(24) NOT NULL DEFAULT 'UNASSIGNED',
    next_follow_up_at TIMESTAMPTZ NULL,
    last_follow_up_at TIMESTAMPTZ NULL,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_renewal_cases_member_cycle
        UNIQUE (member_id, cycle_end_date),
    CONSTRAINT chk_renewal_cases_status
        CHECK (operational_status IN ('UNASSIGNED', 'OPEN', 'WAITING', 'PAUSED')),
    CONSTRAINT chk_renewal_cases_version
        CHECK (version >= 1)
);

CREATE TABLE IF NOT EXISTS renewal_follow_ups (
    id SERIAL PRIMARY KEY,
    renewal_case_id INTEGER NOT NULL
        REFERENCES renewal_cases(id) ON DELETE RESTRICT,
    performed_by_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL,
    contact_method VARCHAR(16) NOT NULL,
    contact_result VARCHAR(24) NOT NULL,
    note VARCHAR(1000) NULL,
    next_follow_up_at TIMESTAMPTZ NULL,
    client_operation_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_renewal_follow_ups_operation
        UNIQUE (client_operation_id),
    CONSTRAINT chk_renewal_follow_ups_method
        CHECK (contact_method IN ('CALL', 'VISIT', 'OTHER')),
    CONSTRAINT chk_renewal_follow_ups_result
        CHECK (contact_result IN (
            'NO_ANSWER', 'REACHED', 'CALL_BACK',
            'NOT_INTERESTED_YET', 'WRONG_NUMBER', 'VISIT_EXPECTED'
        ))
);

CREATE TABLE IF NOT EXISTS renewal_assignment_events (
    id SERIAL PRIMARY KEY,
    renewal_case_id INTEGER NOT NULL
        REFERENCES renewal_cases(id) ON DELETE RESTRICT,
    previous_owner_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL,
    new_owner_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL,
    changed_by_user_id INTEGER NULL
        REFERENCES users(id) ON DELETE SET NULL,
    reason VARCHAR(500) NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_renewal_cases_owner_status_cycle
    ON renewal_cases(owner_user_id, operational_status, cycle_end_date);
CREATE INDEX IF NOT EXISTS idx_renewal_cases_status_next_follow_up_cycle
    ON renewal_cases(operational_status, next_follow_up_at, cycle_end_date);
CREATE INDEX IF NOT EXISTS idx_renewal_follow_ups_case_created
    ON renewal_follow_ups(renewal_case_id, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_renewal_assignment_events_case_created
    ON renewal_assignment_events(renewal_case_id, created_at DESC, id DESC);
