-- J7 / #70: one ValidationResult per execution_attempt.

CREATE UNIQUE INDEX IF NOT EXISTS validation_result_execution_attempt_uniq
    ON domain.validation_result (execution_attempt_id)
    WHERE execution_attempt_id IS NOT NULL;

COMMENT ON INDEX domain.validation_result_execution_attempt_uniq IS
    'J7: at most one ValidationResult per execution_attempt';
