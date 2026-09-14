-- Durable idempotency records for attendance captured while offline.
CREATE TABLE IF NOT EXISTS offline_attendance_operations (
    client_operation_id UUID PRIMARY KEY,
    member_id INTEGER,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username TEXT,
    server_business_date DATE NOT NULL,
    status TEXT NOT NULL,
    result_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMPTZ,
    CONSTRAINT offline_attendance_operations_status_check
        CHECK (status IN ('processing', 'processed')),
    CONSTRAINT offline_attendance_operations_result_check
        CHECK (result_code IN (
            'processing', 'synced', 'duplicate_attendance', 'invalid_member',
            'inactive_membership', 'unauthorized', 'validation_error',
            'temporary_error'
        ))
);

CREATE INDEX IF NOT EXISTS idx_offline_attendance_operations_user_created
    ON offline_attendance_operations(user_id, created_at);

CREATE INDEX IF NOT EXISTS idx_offline_attendance_operations_member_date
    ON offline_attendance_operations(member_id, server_business_date);
