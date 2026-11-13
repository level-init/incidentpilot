"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EvalSnapshotBanner } from "@/components/EvalSnapshotBanner";
import {
  classifyScenarioRun,
  listScenarioRuns,
  type ScenarioRun,
} from "@/lib/eval";

const STATUS_FILTERS = [
  "",
  "PENDING",
  "BASELINE_PASSED",
  "FAULT_INJECTED",
  "FAILED",
  "EVALUATED",
] as const;

export default function EvalRunsPage() {
  const [rows, setRows] = useState<ScenarioRun[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await listScenarioRuns({
        status: status || undefined,
        limit: 100,
      });
      setRows(data);
    } catch (err: unknown) {
      setRows([]);
      setError(err instanceof Error ? err.message : "failed to load");
    }
  }, [status]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell requireEval>
      <EvalSnapshotBanner note="FAILED = invalid run; EVALUATED + passed=false = scored miss." />

      <section className="page-head">
        <div>
          <h1>Scenario runs</h1>
          <p className="lede">
            Scored harness history. Labels distinguish invalid runs from scored
            misses — never treat FAILED as passed=false.
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </section>

      <div className="filters">
        <label>
          Status
          <select
            value={status}
            onChange={(e) => setStatus(e.target.value)}
            aria-label="Filter by status"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s || "all"} value={s}>
                {s || "All"}
              </option>
            ))}
          </select>
        </label>
      </div>

      {error ? <p className="login-error">{error}</p> : null}

      {!rows && !error ? <p>Loading scenario runs…</p> : null}

      {rows ? (
        <div className="table-wrap">
          <table className="data-table eval-table">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Status</th>
                <th>Outcome label</th>
                <th>passed</th>
                <th>API outcome</th>
                <th>Evaluated</th>
              </tr>
            </thead>
            <tbody>
              {rows.length === 0 ? (
                <tr>
                  <td colSpan={6}>No scenario runs.</td>
                </tr>
              ) : (
                rows.map((run) => {
                  const label = classifyScenarioRun(run);
                  return (
                    <tr key={run.id}>
                      <td>
                        <Link
                          href={`/eval/runs/${run.id}`}
                          className="mono-link"
                        >
                          {run.scenario_key}
                        </Link>
                        <div className="mono muted-id">{run.id.slice(0, 8)}…</div>
                      </td>
                      <td>
                        <span className="pill pill-state">{run.status}</span>
                      </td>
                      <td>
                        <span
                          className={`pill pill-outcome pill-outcome-${label.kind}`}
                        >
                          {label.badge}
                        </span>
                      </td>
                      <td className="mono">
                        {run.passed === null
                          ? "null"
                          : run.passed
                            ? "true"
                            : "false"}
                      </td>
                      <td className="mono">{run.outcome}</td>
                      <td className="mono">
                        {run.evaluated_at
                          ? new Date(run.evaluated_at).toLocaleString()
                          : "—"}
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      ) : null}
    </AppShell>
  );
}
