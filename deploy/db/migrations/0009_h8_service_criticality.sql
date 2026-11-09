-- H8 / #54: service criticality feeds the SYSTEM severity updater.

ALTER TABLE domain.service
    ADD COLUMN IF NOT EXISTS criticality text NOT NULL DEFAULT 'MEDIUM';

ALTER TABLE domain.service
    DROP CONSTRAINT IF EXISTS service_criticality_check;

ALTER TABLE domain.service
    ADD CONSTRAINT service_criticality_check CHECK (
        criticality IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW')
    );

-- Demo seed (checkout is customer-facing).
UPDATE domain.service
SET criticality = 'HIGH',
    updated_at = now()
WHERE key = 'checkout'
  AND criticality = 'MEDIUM';
