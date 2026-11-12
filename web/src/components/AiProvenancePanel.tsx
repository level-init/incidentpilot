"use client";

import { useCallback, useEffect, useState } from "react";

import {
  getAiInvocationProvenance,
  listIncidentAiInvocations,
  type AiInvocationProvenance,
  type AiInvocationSummary,
} from "@/lib/api";
import { useSession } from "@/lib/session";

type Props = {
  incidentId: string;
};

export function AiProvenancePanel({ incidentId }: Props) {
  const session = useSession();
  const isAdmin = session.role === "admin";
  const [rows, setRows] = useState<AiInvocationSummary[]>([]);
  const [selected, setSelected] = useState<AiInvocationProvenance | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!isAdmin) return;
    setError(null);
    try {
      setRows(await listIncidentAiInvocations(incidentId));
    } catch (err: unknown) {
      setRows([]);
      setError(err instanceof Error ? err.message : "ai list failed");
    }
  }, [incidentId, isAdmin]);

  useEffect(() => {
    void load();
  }, [load]);

  async function openProvenance(invocationId: string) {
    setBusy(true);
    setError(null);
    try {
      setSelected(await getAiInvocationProvenance(invocationId));
    } catch (err: unknown) {
      setSelected(null);
      setError(err instanceof Error ? err.message : "provenance failed");
    } finally {
      setBusy(false);
    }
  }

  // Viewer/Responder limited — hide lineage entirely (API is admin:config).
  if (!isAdmin) {
    return null;
  }

  return (
    <section className="record-panel provenance-panel" aria-label="AI provenance">
      <header className="timeline-head">
        <div>
          <h2>AI provenance</h2>
          <span className="metric-label">Admin only · evidence lineage</span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      <p className="lede">
        Open an invocation to inspect input Evidence IDs, artifact URI, and
        metadata. Viewers and responders cannot access this surface.
      </p>

      {error ? <p className="login-error">{error}</p> : null}

      {rows.length === 0 ? (
        <p className="meta-note">No AI invocations for this incident.</p>
      ) : (
        <ul className="admin-version-list">
          {rows.map((row) => (
            <li key={row.invocation_id}>
              <span className="mono">
                {row.purpose} · {row.provider}/{row.model} · {row.status}
              </span>{" "}
              <button
                type="button"
                className="btn-ghost"
                disabled={busy}
                onClick={() => void openProvenance(row.invocation_id)}
              >
                Open lineage
              </button>
            </li>
          ))}
        </ul>
      )}

      {selected ? (
        <div className="provenance-detail">
          <p className="metric-label">
            Lineage · {selected.invocation_id}
          </p>
          <dl className="detail-grid">
            <div>
              <dt>Purpose</dt>
              <dd className="mono">{selected.purpose}</dd>
            </div>
            <div>
              <dt>Model</dt>
              <dd className="mono">
                {selected.provider}/{selected.model}
              </dd>
            </div>
            <div>
              <dt>Status</dt>
              <dd>
                <span className="pill">{selected.status}</span>
              </dd>
            </div>
            <div>
              <dt>Artifact</dt>
              <dd className="mono">{selected.artifact_uri ?? "—"}</dd>
            </div>
          </dl>
          <p className="metric-label">Input evidence IDs</p>
          {selected.input_evidence_ids.length === 0 ? (
            <p className="meta-note">None recorded.</p>
          ) : (
            <ul className="admin-version-list">
              {selected.input_evidence_ids.map((id) => (
                <li key={id}>
                  <a className="mono" href={`#evidence-${id}`}>
                    {id}
                  </a>
                </li>
              ))}
            </ul>
          )}
          <pre className="scope-json">
            {JSON.stringify(
              {
                request_metadata: selected.request_metadata,
                response_metadata: selected.response_metadata,
                prompt_hash: selected.prompt_hash,
                response_hash: selected.response_hash,
                tokens: {
                  input: selected.input_tokens,
                  output: selected.output_tokens,
                },
                latency_ms: selected.latency_ms,
                error_summary: selected.error_summary,
              },
              null,
              2,
            )}
          </pre>
        </div>
      ) : null}
    </section>
  );
}
