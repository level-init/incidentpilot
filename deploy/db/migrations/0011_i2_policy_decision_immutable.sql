-- I2 / #58: PolicyDecision rows are immutable once written.

CREATE OR REPLACE FUNCTION domain.policy_decision_forbid_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'policy_decision is immutable: % forbidden', TG_OP
        USING ERRCODE = 'integrity_constraint_violation';
END;
$$;

DROP TRIGGER IF EXISTS policy_decision_forbid_update ON domain.policy_decision;
CREATE TRIGGER policy_decision_forbid_update
    BEFORE UPDATE ON domain.policy_decision
    FOR EACH ROW
    EXECUTE FUNCTION domain.policy_decision_forbid_mutation();

DROP TRIGGER IF EXISTS policy_decision_forbid_delete ON domain.policy_decision;
CREATE TRIGGER policy_decision_forbid_delete
    BEFORE DELETE ON domain.policy_decision
    FOR EACH ROW
    EXECUTE FUNCTION domain.policy_decision_forbid_mutation();
