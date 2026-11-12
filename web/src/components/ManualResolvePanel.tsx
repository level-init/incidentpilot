"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  fetchResolveContext,
  manualResolve,
  type ResolveContext,
} from "@/lib/api";
import { useSession } from "@/lib/session";

type Props = {
  incidentId: string;
  onResolved?: () => void;
};

export function ManualResolvePanel({ incidentId, onResolved }: Props) {
  const session = useSession();
  const canWrite =
    session.role === "responder" || session.role === "admin";
  const [ctx, setCtx] = useState<ResolveContext | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setError(null);
    try {
      setCtx(await fetchResolveContext(incidentId));
    } catch (err: unknown) {
      setCtx(null);
      setError(err instanceof Error ? err.message : "resolve context failed");
    }
  }, [incidentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    if (!ctx?.eligible || !reason.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await manualResolve(incidentId, {
        reason: reason.trim(),
        expected_revision: ctx.incident_revision,
      });
      setReason("");
      onResolved?.();
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "resolve failed");
    } finally {
      setBusy(false);
    }
  }

  // No generic Resolve — hide entirely when guards fail.
  if (!ctx?.eligible) {
    return null;
  }

  const health = ctx.health;

  return (
    <section className="manual-resolve" aria-label="Contextual manual resolve">
      <header className="timeline-head">
        <div>
          <h2>Manual resolve</h2>
          <span className="metric-label">
            contextual · RECOVERED only · audited
          </span>
        </div>
      </header>
      <p className="lede">{ctx.message}</p>

      <div className="health-block">
        <p className="metric-label">Validation health</p>
        {health?.outcome ? (
          <>
            <span className="pill pill-state">{health.outcome}</span>
            {health.decided_at ? (
              <time className="mono meta-note" dateTime={health.decided_at}>
                {new Date(health.decided_at).toLocaleString()}
              </time>
            ) : null}
            {Object.keys(health.observations).length > 0 ? (
              <pre className="scope-json">
                {JSON.stringify(health.observations, null, 2)}
              </pre>
            ) : null}
          </>
        ) : (
          <p className="meta-note">No ValidationResult on file.</p>
        )}
      </div>

      {error ? <p className="login-error">{error}</p> : null}

      {canWrite ? (
        <form className="observe-form" onSubmit={onSubmit}>
          <label htmlFor="resolve-reason">Reason (required)</label>
          <textarea
            id="resolve-reason"
            rows={3}
            value={reason}
            placeholder="Why is this safe to mark RESOLVED?"
            onChange={(e) => setReason(e.target.value)}
          />
          <button
            type="submit"
            className="btn-primary observe-submit"
            disabled={busy || !reason.trim()}
          >
            {busy ? "Resolving…" : "Resolve manually"}
          </button>
        </form>
      ) : (
        <p className="pane-hint">Viewer cannot resolve — Responder+ required.</p>
      )}
    </section>
  );
}
