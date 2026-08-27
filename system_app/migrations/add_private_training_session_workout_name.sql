ALTER TABLE private_training_sessions
ADD COLUMN IF NOT EXISTS workout_name VARCHAR(255) NULL;
