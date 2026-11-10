-- J9 / #72: Compensation Action linked to parent; never inherits approval.

ALTER TABLE domain.action
    ADD COLUMN IF NOT EXISTS compensates_action_id uuid
        REFERENCES domain.action (id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS compensates_action_version integer;

ALTER TABLE domain.action
    DROP CONSTRAINT IF EXISTS action_compensates_version_positive;

ALTER TABLE domain.action
    ADD CONSTRAINT action_compensates_version_positive CHECK (
        compensates_action_version IS NULL OR compensates_action_version >= 1
    );

ALTER TABLE domain.action
    DROP CONSTRAINT IF EXISTS action_compensates_pair_check;

ALTER TABLE domain.action
    ADD CONSTRAINT action_compensates_pair_check CHECK (
        (compensates_action_id IS NULL AND compensates_action_version IS NULL)
        OR (compensates_action_id IS NOT NULL AND compensates_action_version IS NOT NULL)
    );

CREATE INDEX IF NOT EXISTS action_compensates_action_id_idx
    ON domain.action (compensates_action_id)
    WHERE compensates_action_id IS NOT NULL;

COMMENT ON COLUMN domain.action.compensates_action_id IS
    'J9: parent Action this compensation reverses; fresh PolicyDecision/Approval required';
