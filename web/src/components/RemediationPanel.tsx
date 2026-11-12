"use client";

import { useCallback, useEffect, useState } from "react";

import {
  ApiError,
  decideApproval,
  listRemediation,
  type RemediationAction,
} from "@/lib/api";
import { useSession } from "@/lib/session";

type Props = {
  incidentId: string;
};

function ScopeBlock({
  parameters,
  targetRef,
}: {
  parameters: Record<string, unknown>;
  targetRef: Record<string, unknown>;
}) {
  return (
    <div className="remediation-scope">
      <p className="metric-label">Scope (review before approve)</p>
      <div className="scope-grid">
        <div>
          <span className="metric-label">Parameters</span>
          <pre className="scope-json">
            {JSON.stringify(parameters, null, 2)}
          </pre>
        </div>
        <div>
          <span className="metric-label">Target</span>
          <pre className="scope-json">{JSON.stringify(targetRef, null, 2)}</pre>
        </div>
      </div>
    </div>
  );
}

export function RemediationPanel({ incidentId }: Props) {
  const session = useSession();
  const canDecide =
    session.role === "responder" || session.role === "admin";
  const [cards, setCards] = useState<RemediationAction[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setCards(await listRemediation(incidentId));
    } catch (err: unknown) {
      setCards([]);
      setError(err instanceof Error ? err.message : "failed to load remediation");
    }
  }, [incidentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDecide(
    approvalId: string,
    status: "APPROVED" | "REJECTED",
    actionVersion: number,
  ) {
    setBusyId(approvalId);
    setError(null);
    setStale(false);
    try {
      await decideApproval(approvalId, status, actionVersion);
      // Success: silent refresh — no success toast (M10).
      await load();
    } catch (err: unknown) {
      const staleHit = err instanceof ApiError && err.isStale;
      setStale(staleHit);
      setError(
        staleHit
          ? "Stale action version — approval rejected. Panel refreshed; review and retry."
          : err instanceof Error
            ? err.message
            : "decide failed",
      );
      // Always refresh on failure so UI matches SoR (buttons may disappear).
      await load();
    } finally {
      setBusyId(null);
    }
  }

  return (
    <section className="remediation-panel" aria-label="Remediation">
      <header className="timeline-head">
        <div>
          <h2>Remediation</h2>
          <span className="metric-label">
            action · version · params · risk · policy · approval · attempt
          </span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {stale ? (
        <div className="stale-banner" role="alert">
          <strong>Stale version rejected</strong>
          <p>{error}</p>
        </div>
      ) : error ? (
        <p className="login-error">{error}</p>
      ) : null}

      {cards === null ? (
        <p>Loading remediation…</p>
      ) : cards.length === 0 ? (
        <p className="lede">No remediation actions for this incident.</p>
      ) : (
        <ul className="remediation-list">
          {cards.map((card) => {
            const pending =
              card.approval?.status === "PENDING" &&
              card.policy?.decision === "REQUIRE_APPROVAL";
            const unsafeAttempts = card.attempts.filter((a) => a.unsafe_to_retry);
            return (
              <li key={card.action_id} className="remediation-card">
                <div className="pane-item-top">
                  <span className="pill pill-state">{card.action_type}</span>
                  <span className="pill">v{card.current_version}</span>
                  <span className="pill">{card.status}</span>
                  <span
                    className={
                      card.risk === "irreversible"
                        ? "chip chip-risk-high"
                        : "chip"
                    }
                  >
                    risk: {card.risk}
                  </span>
                </div>

                <ScopeBlock
                  parameters={card.parameters}
                  targetRef={card.target_ref}
                />

                <dl className="remediation-meta">
                  <div>
                    <dt>Policy</dt>
                    <dd>
                      {card.policy ? (
                        <>
                          <span className="pill">{card.policy.decision}</span>
                          {card.policy.reason ? (
                            <span className="meta-note">{card.policy.reason}</span>
                          ) : null}
                          {card.policy.policy_key ? (
                            <span className="mono meta-note">
                              {card.policy.policy_key}@
                              {card.policy.policy_version ?? "?"}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                  <div>
                    <dt>Approval</dt>
                    <dd>
                      {card.approval ? (
                        <>
                          <span className="pill">{card.approval.status}</span>
                          {card.approval.decided_by ? (
                            <span className="mono meta-note">
                              {card.approval.decided_by}
                            </span>
                          ) : null}
                        </>
                      ) : (
                        "—"
                      )}
                    </dd>
                  </div>
                </dl>

                {unsafeAttempts.length > 0 ? (
                  <div className="unsafe-banner" role="status">
                    <strong>Unsafe to retry</strong>
                    <p>
                      Reconcile state is UNKNOWN or PARTIAL (or attempt state
                      UNKNOWN) — not a plain failure. Do not blind-retry.
                    </p>
                    <ul>
                      {unsafeAttempts.map((a) => (
                        <li key={a.id} className="mono">
                          attempt #{a.attempt_number}: state={a.state}
                          {a.reconciliation_state
                            ? ` · reconcile=${a.reconciliation_state}`
                            : ""}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {card.attempts.length > 0 ? (
                  <div className="attempt-block">
                    <p className="metric-label">Execution attempts</p>
                    <ul className="attempt-list">
                      {card.attempts.map((a) => (
                        <li
                          key={a.id}
                          className={
                            a.unsafe_to_retry
                              ? "attempt-row attempt-unsafe"
                              : "attempt-row"
                          }
                        >
                          <span className="mono">#{a.attempt_number}</span>
                          <span
                            className={
                              a.unsafe_to_retry
                                ? "pill pill-unsafe"
                                : "pill"
                            }
                          >
                            {a.unsafe_to_retry
                              ? `UNSAFE · ${a.state}`
                              : a.state}
                          </span>
                          {a.reconciliation_state ? (
                            <span className="mono">
                              reconcile={a.reconciliation_state}
                            </span>
                          ) : null}
                          {a.error_summary ? (
                            <span className="meta-note">{a.error_summary}</span>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </div>
                ) : null}

                {pending && card.approval ? (
                  <div className="approve-row">
                    {canDecide ? (
                      <>
                        <button
                          type="button"
                          className="btn-primary observe-submit"
                          disabled={busyId === card.approval.id}
                          onClick={() =>
                            void onDecide(
                              card.approval!.id,
                              "APPROVED",
                              card.approval!.action_version,
                            )
                          }
                        >
                          Approve v{card.approval.action_version}
                        </button>
                        <button
                          type="button"
                          className="btn-ghost"
                          disabled={busyId === card.approval.id}
                          onClick={() =>
                            void onDecide(
                              card.approval!.id,
                              "REJECTED",
                              card.approval!.action_version,
                            )
                          }
                        >
                          Reject
                        </button>
                      </>
                    ) : (
                      <p className="pane-hint">
                        Viewer cannot approve — Responder+ required.
                      </p>
                    )}
                  </div>
                ) : null}
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
