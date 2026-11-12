"use client";

import { useCallback, useEffect, useState } from "react";

import { listAdminIntegrations, type IntegrationStatus } from "@/lib/api";

export function AdminIntegrationsPanel() {
  const [rows, setRows] = useState<IntegrationStatus[]>([]);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setRows(await listAdminIntegrations());
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "integrations load failed");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <section className="admin-section" aria-label="Integrations">
      <header className="timeline-head">
        <div>
          <h2>Integrations</h2>
          <span className="metric-label">scope + health · secrets never shown</span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      <p className="lede">
        Connector configuration metadata only. Secret values (tokens, signing
        secrets, passwords) are never returned by the API.
      </p>

      {error ? <p className="login-error">{error}</p> : null}

      <ul className="integration-list">
        {rows.map((row) => (
          <li key={row.key} className="integration-card">
            <div className="integration-head">
              <h3>{row.display_name}</h3>
              <span className={`pill ${row.configured ? "pill-ok" : ""}`}>
                {row.configured ? "configured" : "not configured"}
              </span>
              <span className="pill">{row.kind}</span>
              {row.secrets_exposed ? (
                <span className="pill pill-danger">secrets exposed</span>
              ) : (
                <span className="pill">secrets redacted</span>
              )}
            </div>
            {row.endpoint ? (
              <p className="mono meta-note">{row.endpoint}</p>
            ) : null}
            {row.notes ? <p className="meta-note">{row.notes}</p> : null}
            <pre className="scope-json">{JSON.stringify(row.scope, null, 2)}</pre>
          </li>
        ))}
      </ul>
    </section>
  );
}
