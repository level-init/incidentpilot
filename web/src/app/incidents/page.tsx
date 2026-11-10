"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  formatDuration,
  listIncidents,
  overviewMetrics,
  type Incident,
} from "@/lib/api";

const STATE_OPTIONS = [
  "",
  "DETECTED",
  "TRIAGING",
  "INVESTIGATING",
  "DIAGNOSED",
  "AWAITING_APPROVAL",
  "MITIGATING",
  "VALIDATING",
  "DEGRADED",
  "PLANNING_REMEDIATION",
  "RESOLVED",
  "POSTMORTEM",
  "CLOSED",
] as const;

export default function IncidentsPage() {
  const [rows, setRows] = useState<Incident[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState("");
  const [severity, setSeverity] = useState("");
  const [service, setService] = useState("");
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await listIncidents({
        state: state || undefined,
        severity: severity || undefined,
        service: service.trim() || undefined,
      });
      setRows(data);
      setNowMs(Date.now());
    } catch (err: unknown) {
      setRows([]);
      setError(err instanceof Error ? err.message : "failed to load");
    }
  }, [severity, service, state]);

  useEffect(() => {
    void load();
  }, [load]);

  const metrics = useMemo(
    () => overviewMetrics(rows ?? []),
    [rows],
  );

  const severityOptions = useMemo(() => {
    const set = new Set<string>();
    for (const row of rows ?? []) {
      if (row.severity) set.add(row.severity);
    }
    if (severity) set.add(severity);
    return ["", ...[...set].sort()];
  }, [rows, severity]);

  return (
    <AppShell>
      <section className="page-head">
        <div>
          <h1>Incidents</h1>
          <p className="lede">
            Overview metrics and a filterable list — severity, state, service,
            duration.
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </section>

      <section className="metrics" aria-label="Overview metrics">
        <div className="metric">
          <span className="metric-label">Listed</span>
          <span className="metric-value">{metrics.total}</span>
        </div>
        <div className="metric">
          <span className="metric-label">Active</span>
          <span className="metric-value">{metrics.active}</span>
        </div>
        <div className="metric metric-wide">
          <span className="metric-label">Active by state</span>
          <span className="metric-chips">
            {metrics.byState.length === 0
              ? "—"
              : metrics.byState.map(([s, n]) => (
                  <span key={s} className="chip">
                    {s} · {n}
                  </span>
                ))}
          </span>
        </div>
        <div className="metric metric-wide">
          <span className="metric-label">Active by severity</span>
          <span className="metric-chips">
            {metrics.bySeverity.length === 0
              ? "—"
              : metrics.bySeverity.map(([s, n]) => (
                  <span key={s} className="chip">
                    {s} · {n}
                  </span>
                ))}
          </span>
        </div>
      </section>

      <section className="filters" aria-label="Filters">
        <label>
          State
          <select value={state} onChange={(e) => setState(e.target.value)}>
            {STATE_OPTIONS.map((s) => (
              <option key={s || "all"} value={s}>
                {s || "Any"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Severity
          <select
            value={severity}
            onChange={(e) => setSeverity(e.target.value)}
          >
            {severityOptions.map((s) => (
              <option key={s || "all"} value={s}>
                {s || "Any"}
              </option>
            ))}
          </select>
        </label>
        <label>
          Service
          <input
            value={service}
            placeholder="e.g. checkout"
            onChange={(e) => setService(e.target.value)}
          />
        </label>
      </section>

      {error ? <p className="login-error">{error}</p> : null}

      <div className="table-wrap">
        <table className="incident-table">
          <thead>
            <tr>
              <th>ID</th>
              <th>Title</th>
              <th>Severity</th>
              <th>State</th>
              <th>Service</th>
              <th>Duration</th>
            </tr>
          </thead>
          <tbody>
            {rows === null ? (
              <tr>
                <td colSpan={6}>Loading…</td>
              </tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={6}>No incidents match these filters.</td>
              </tr>
            ) : (
              rows.map((row) => (
                <tr key={row.id}>
                  <td>
                    <Link
                      className="mono-link"
                      href={`/incidents/${row.public_id}`}
                    >
                      {row.public_id}
                    </Link>
                  </td>
                  <td>{row.title}</td>
                  <td>
                    <span className="pill">{row.severity ?? "—"}</span>
                  </td>
                  <td>
                    <span className="pill pill-state">{row.state}</span>
                  </td>
                  <td className="mono">
                    {row.service_keys.length
                      ? row.service_keys.join(", ")
                      : "—"}
                  </td>
                  <td className="mono">
                    {formatDuration(
                      row.opened_at,
                      row.resolved_at,
                      row.closed_at,
                      nowMs,
                    )}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </AppShell>
  );
}
