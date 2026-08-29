-- Private Training Phase: Outcomer / Private-only client support

ALTER TABLE private_training_subscriptions
    ADD COLUMN IF NOT EXISTS client_type VARCHAR(20);

ALTER TABLE private_training_subscriptions
    ADD COLUMN IF NOT EXISTS client_name TEXT;

ALTER TABLE private_training_subscriptions
    ADD COLUMN IF NOT EXISTS client_phone TEXT;

ALTER TABLE private_training_subscriptions
    ALTER COLUMN member_id DROP NOT NULL;

ALTER TABLE private_training_subscriptions
    ALTER COLUMN client_type SET DEFAULT 'MEMBER';

UPDATE private_training_subscriptions
SET client_type = COALESCE(NULLIF(btrim(client_type), ''), 'MEMBER');

UPDATE private_training_subscriptions s
SET
    client_name = COALESCE(NULLIF(btrim(s.client_name), ''), m.name),
    client_phone = COALESCE(NULLIF(btrim(s.client_phone), ''), COALESCE(m.phone, '')),
    client_type = COALESCE(NULLIF(btrim(s.client_type), ''), 'MEMBER')
FROM members m
WHERE s.member_id = m.id;

UPDATE private_training_subscriptions
SET
    client_name = COALESCE(NULLIF(btrim(client_name), ''), ''),
    client_phone = COALESCE(NULLIF(btrim(client_phone), ''), '')
WHERE client_name IS NULL OR client_phone IS NULL;

ALTER TABLE private_training_subscriptions
    ALTER COLUMN client_type SET NOT NULL;

ALTER TABLE private_training_subscriptions
    ALTER COLUMN client_name SET NOT NULL;

ALTER TABLE private_training_subscriptions
    ALTER COLUMN client_phone SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_private_training_subscriptions_client_type'
    ) THEN
        ALTER TABLE private_training_subscriptions
        ADD CONSTRAINT chk_private_training_subscriptions_client_type
        CHECK (client_type IN ('MEMBER', 'OUTCOMER'));
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_private_training_subscriptions_client_identity'
    ) THEN
        ALTER TABLE private_training_subscriptions
        ADD CONSTRAINT chk_private_training_subscriptions_client_identity
        CHECK (
            (client_type = 'MEMBER' AND member_id IS NOT NULL)
            OR (
                client_type = 'OUTCOMER'
                AND member_id IS NULL
                AND length(btrim(COALESCE(client_name, ''))) > 0
                AND length(btrim(COALESCE(client_phone, ''))) > 0
            )
        );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_private_training_subscriptions_client_type_phone
    ON private_training_subscriptions(client_type, client_phone);
