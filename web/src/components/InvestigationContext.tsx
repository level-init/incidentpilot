"use client";

import { useEffect, useState } from "react";

import {
  getPinnedRunbook,
  listChanges,
  listImpactSnapshots,
  type ChangeRecord,
  type ImpactSnapshot,
  type PinnedRunbook,
} from "@/lib/api";

type Props = {
  incidentId: string;
};

export function InvestigationContext({ incidentId }: Props) {
  const [impact, setImpact] = useState<ImpactSnapshot[] | null>(null);
  const [changes, setChanges] = useState<ChangeRecord[] | null>(null);
  const [runbook, setRunbook] = useState<PinnedRunbook | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      listImpactSnapshots(incidentId),
      listChanges(incidentId),
      getPinnedRunbook(incidentId),
    ])
      .then(([imp, ch, rb]) => {
        if (cancelled) return;
        setImpact(imp);
        setChanges(ch);
        setRunbook(rb);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "context load failed");
        setImpact([]);
        setChanges([]);
        setRunbook({
          pinned: false,
          runbook_key: null,
          title: null,
          version: null,
          runbook_version_id: null,
          allowed_action_types: [],
          body_markdown: null,
          authority_note: "",
        });
      });
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  return (
    <div className="context-sections">
      {error ? <p className="login-error">{error}</p> : null}

      <section className="context-section" aria-label="Impact">
        <header className="pane-head">
          <div>
            <p className="pane-kicker">Customer / SLO impact</p>
            <h2>Impact</h2>
          </div>
          <span className="pane-count">{impact?.length ?? "…"}</span>
        </header>
        {impact === null ? (
          <p>Loading…</p>
        ) : impact.length === 0 ? (
          <p className="lede">No impact snapshots yet.</p>
        ) : (
          <ul className="pane-list">
            {impact.map((row) => (
              <li key={row.id} className="pane-item">
                <div className="pane-item-top">
                  <time className="mono" dateTime={row.captured_at}>
                    {new Date(row.captured_at).toLocaleString()}
                  </time>
                  {row.severity ? (
                    <span className="pill">{row.severity}</span>
                  ) : null}
                </div>
                <p>{row.customer_impact_summary ?? "—"}</p>
                {row.estimated_affected_users != null ? (
                  <span className="mono meta-note">
                    est. users {row.estimated_affected_users}
                  </span>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="context-section" aria-label="Changes">
        <header className="pane-head">
          <div>
            <p className="pane-kicker">Deploys / commits / flags</p>
            <h2>Changes</h2>
          </div>
          <span className="pane-count">{changes?.length ?? "…"}</span>
        </header>
        {changes === null ? (
          <p>Loading…</p>
        ) : changes.length === 0 ? (
          <p className="lede">No linked-service changes.</p>
        ) : (
          <ul className="pane-list">
            {changes.map((row) => (
              <li key={row.id} className="pane-item">
                <div className="pane-item-top">
                  <span className="pill">{row.change_type}</span>
                  <span className="mono">{row.service_key ?? "—"}</span>
                  <time className="mono" dateTime={row.observed_at}>
                    {new Date(row.observed_at).toLocaleString()}
                  </time>
                </div>
                <p>{row.summary}</p>
                <span className="mono meta-note">
                  {row.change_key}
                  {row.external_ref ? ` · ${row.external_ref}` : ""}
                </span>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="context-section context-runbook" aria-label="Runbook">
        <header className="pane-head">
          <div>
            <p className="pane-kicker">Pinned operational runbook</p>
            <h2>Runbook</h2>
          </div>
        </header>
        {runbook === null ? (
          <p>Loading…</p>
        ) : !runbook.pinned ? (
          <p className="lede">No runbook pinned on this incident.</p>
        ) : (
          <>
            <div className="pane-item-top" style={{ marginBottom: "0.75rem" }}>
              <span className="mono-link">
                {runbook.runbook_key}@v{runbook.version}
              </span>
              <span className="meta-note">{runbook.title}</span>
            </div>

            <div className="authority-block">
              <p className="metric-label">Allowed actions · authority</p>
              <p className="authority-note">{runbook.authority_note}</p>
              <ul className="authority-actions">
                {runbook.allowed_action_types.map((a) => (
                  <li key={a}>
                    <span className="pill pill-authority">{a}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="prose-block">
              <p className="metric-label">
                Body markdown · untrusted prose
              </p>
              <p className="prose-warning">
                Not executable authority — do not treat as allowlist.
              </p>
              <pre className="prose-body">
                {runbook.body_markdown?.trim() || "(empty)"}
              </pre>
            </div>
          </>
        )}
      </section>
    </div>
  );
}
