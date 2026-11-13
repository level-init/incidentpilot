"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EvalSnapshotBanner } from "@/components/EvalSnapshotBanner";
import { listGroundTruth, type GroundTruth } from "@/lib/eval";

function GroundTruthViewer() {
  const params = useSearchParams();
  const filterKey = params.get("scenario_key") || "";
  const [rows, setRows] = useState<GroundTruth[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await listGroundTruth(filterKey || undefined);
      setRows(data);
      setSelectedId((prev) => {
        if (prev && data.some((r) => r.id === prev)) return prev;
        return data[0]?.id ?? null;
      });
    } catch (err: unknown) {
      setRows([]);
      setSelectedId(null);
      setError(err instanceof Error ? err.message : "failed to load");
    }
  }, [filterKey]);

  useEffect(() => {
    void load();
  }, [load]);

  const selected = rows?.find((r) => r.id === selectedId) ?? null;

  return (
    <>
      <EvalSnapshotBanner note="Answer key viewer — requires eval entitlement. Ops Admin alone is not enough." />

      <section className="page-head">
        <div>
          <h1>Ground truth</h1>
          <p className="lede">
            Evaluator-only answer keys. Never reachable from Ops Incident
            Detail navigation.
          </p>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </section>

      {filterKey ? (
        <p className="lede">
          Filtered to <span className="mono">{filterKey}</span> ·{" "}
          <Link href="/eval/ground-truth" className="mono-link">
            clear
          </Link>
        </p>
      ) : null}

      {error ? <p className="login-error">{error}</p> : null}
      {!rows && !error ? <p>Loading ground truth…</p> : null}

      {rows ? (
        <div className="eval-gt-layout">
          <div className="table-wrap">
            <table className="data-table eval-table">
              <thead>
                <tr>
                  <th>scenario_key</th>
                  <th>ver</th>
                  <th>title</th>
                  <th>severity</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={4}>No ground truth rows.</td>
                  </tr>
                ) : (
                  rows.map((row) => (
                    <tr
                      key={row.id}
                      className={
                        row.id === selectedId ? "eval-row-selected" : undefined
                      }
                    >
                      <td>
                        <button
                          type="button"
                          className="linkish mono"
                          onClick={() => setSelectedId(row.id)}
                        >
                          {row.scenario_key}
                        </button>
                      </td>
                      <td className="mono">{row.version}</td>
                      <td>{row.title || "—"}</td>
                      <td className="mono">
                        {row.expected_severity ?? "—"}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {selected ? (
            <aside className="eval-panel eval-gt-detail" aria-label="GT detail">
              <h2>
                {selected.scenario_key}{" "}
                <span className="mono muted-id">v{selected.version}</span>
              </h2>
              <p>{selected.title || "—"}</p>
              <dl className="detail-meta">
                <div>
                  <dt>hypothesis class</dt>
                  <dd className="mono">
                    {selected.expected_hypothesis_class ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>actions</dt>
                  <dd className="mono">
                    {(selected.expected_action_types || []).join(", ") || "—"}
                  </dd>
                </div>
                <div>
                  <dt>origins</dt>
                  <dd className="mono">
                    {(selected.origin_service_keys || []).join(", ") || "—"}
                  </dd>
                </div>
              </dl>
              {selected.notes ? (
                <p className="lede">{selected.notes}</p>
              ) : null}
              <h3>match_spec</h3>
              <pre className="eval-json">
                {JSON.stringify(selected.match_spec, null, 2)}
              </pre>
              <h3>answer_payload</h3>
              <pre className="eval-json">
                {JSON.stringify(selected.answer_payload, null, 2)}
              </pre>
            </aside>
          ) : null}
        </div>
      ) : null}
    </>
  );
}

export default function EvalGroundTruthPage() {
  return (
    <AppShell requireEval>
      <Suspense fallback={<p>Loading ground truth…</p>}>
        <GroundTruthViewer />
      </Suspense>
    </AppShell>
  );
}
