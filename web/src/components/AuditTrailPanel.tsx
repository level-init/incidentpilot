"use client";

import { useCallback, useEffect, useState } from "react";

import { listAudit, type AuditEvent } from "@/lib/api";

type Props = {
  incidentId: string;
};

export function AuditTrailPanel({ incidentId }: Props) {
  const [rows, setRows] = useState<AuditEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await listAudit(incidentId, "asc"));
    } catch (err: unknown) {
      setRows([]);
      setError(err instanceof Error ? err.message : "audit load failed");
    }
  }, [incidentId]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="record-panel" aria-label="Audit trail">
      <header className="timeline-head">
        <div>
          <h2>Audit</h2>
          <span className="metric-label">
            compliance trail · not timeline · oldest first
          </span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {error ? <p className="login-error">{error}</p> : null}

      {rows === null ? (
        <p>Loading audit…</p>
      ) : rows.length === 0 ? (
        <p className="lede">No audit events for this incident.</p>
      ) : (
        <ol className="timeline-list audit-list">
          {rows.map((ev) => (
            <li key={ev.id}>
              <time dateTime={ev.occurred_at} className="mono">
                {new Date(ev.occurred_at).toLocaleString()}
              </time>
              <span className="chip">{ev.action}</span>
              <span className={`pill ${ev.outcome === "success" ? "pill-ok" : ""}`}>
                {ev.outcome}
              </span>
              <p>
                <span className="mono">{ev.actor}</span> · {ev.resource_type}
                {ev.resource_id ? (
                  <span className="mono"> · {ev.resource_id}</span>
                ) : null}
              </p>
              <button
                type="button"
                className="btn-ghost"
                onClick={() =>
                  setExpanded((cur) => (cur === ev.id ? null : ev.id))
                }
              >
                {expanded === ev.id ? "Hide details" : "Details"}
              </button>
              {expanded === ev.id ? (
                <pre className="scope-json">
                  {JSON.stringify(ev.details, null, 2)}
                </pre>
              ) : null}
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
