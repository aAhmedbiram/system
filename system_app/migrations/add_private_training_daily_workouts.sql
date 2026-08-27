-- Private Training Phase 2A: Daily Workout name

CREATE TABLE IF NOT EXISTS private_training_daily_workouts (
    id SERIAL PRIMARY KEY,
    subscription_id INTEGER NOT NULL REFERENCES private_training_subscriptions(id) ON DELETE RESTRICT,
    workout_date DATE NOT NULL,
    workout_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_private_training_daily_workouts_subscription_date UNIQUE (subscription_id, workout_date)
);
