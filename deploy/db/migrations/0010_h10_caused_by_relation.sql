-- H10 / #56: CAUSED_BY is SYSTEM-only under confirmation rules.

ALTER TABLE domain.evidence_relation
    DROP CONSTRAINT IF EXISTS evidence_relation_type_check;

ALTER TABLE domain.evidence_relation
    ADD CONSTRAINT evidence_relation_type_check CHECK (
        relation_type IN (
            'SUPPORTS',
            'CONTRADICTS',
            'DERIVED_FROM',
            'SAME_SIGNAL',
            'TEMPORAL_NEAR',
            'CAUSED_BY'
        )
    );
