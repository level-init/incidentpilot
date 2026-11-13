"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import { EvalSnapshotBanner } from "@/components/EvalSnapshotBanner";
import {
  classifyScenarioRun,
  getEvaluationFamily,
  getOperationalEvaluationForRun,
  getPostmortemEvaluationForRun,
  getScenarioRun,
  type EvaluationFamily,
  type OperationalEvaluation,
  type PostmortemEvaluation,
  type ScenarioRun,
} from "@/lib/eval";

export default function EvalRunDetailPage() {
  const params = useParams<{ id: string }>();
  const runId = params?.id ?? "";
  const [run, setRun] = useState<ScenarioRun | null>(null);
  const [family, setFamily] = useState<EvaluationFamily | null>(null);
  const [opsEval, setOpsEval] = useState<OperationalEvaluation | null>(null);
  const [pmEval, setPmEval] = useState<PostmortemEvaluation | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!runId) return;
    setError(null);
    try {
      const [r, fam, ops, pm] = await Promise.all([
        getScenarioRun(runId),
        getEvaluationFamily(runId),
        getOperationalEvaluationForRun(runId),
        getPostmortemEvaluationForRun(runId),
      ]);
      setRun(r);
      setFamily(fam);
      setOpsEval(ops);
      setPmEval(pm);
    } catch (err: unknown) {
      setRun(null);
      setFamily(null);
      setOpsEval(null);
      setPmEval(null);
      setError(err instanceof Error ? err.message : "failed to load");
    }
  }, [runId]);

  useEffect(() => {
    void load();
  }, [load]);

  const label = run ? classifyScenarioRun(run) : null;
  const linkedIncidentId = opsEval?.incident_id ?? pmEval?.incident_id ?? null;

  return (
    <AppShell requireEval>
      <EvalSnapshotBanner note={label?.detail} />

      <p className="detail-back">
        <Link href="/eval" className="mono-link">
          ← Scenario runs
        </Link>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </p>

      {error ? <p className="login-error">{error}</p> : null}
      {!run && !error ? <p>Loading scenario run…</p> : null}

      {run && label ? (
        <>
          <header className="detail-header eval-detail-header" aria-label="Run header">
            <div className="detail-title-row">
              <h1>{run.scenario_key}</h1>
              <span className={`pill pill-outcome pill-outcome-${label.kind}`}>
                {label.badge}
              </span>
              <span className="pill pill-state">{run.status}</span>
            </div>
            <p className="eval-headline">{label.headline}</p>
            <dl className="detail-meta">
              <div>
                <dt>Run id</dt>
                <dd className="mono">{run.id}</dd>
              </div>
              <div>
                <dt>passed</dt>
                <dd className="mono">
                  {run.passed === null
                    ? "null"
                    : run.passed
                      ? "true"
                      : "false"}
                </dd>
              </div>
              <div>
                <dt>API outcome</dt>
                <dd className="mono">{run.outcome}</dd>
              </div>
              <div>
                <dt>failure_kind</dt>
                <dd className="mono">{run.failure_kind ?? "—"}</dd>
              </div>
              <div>
                <dt>baseline_ok</dt>
                <dd className="mono">
                  {run.baseline_ok === null
                    ? "null"
                    : run.baseline_ok
                      ? "true"
                      : "false"}
                </dd>
              </div>
              <div>
                <dt>evaluated_at</dt>
                <dd className="mono">
                  {run.evaluated_at
                    ? new Date(run.evaluated_at).toLocaleString()
                    : "—"}
                </dd>
              </div>
            </dl>
            {run.failure_detail ? (
              <p className="eval-failure-detail">
                <strong>failure_detail:</strong> {run.failure_detail}
              </p>
            ) : null}
          </header>

          <section className="eval-panel" aria-label="Environment manifest pin">
            <h2>Environment manifest (pinned)</h2>
            {run.environment_manifest ? (
              <dl className="detail-meta">
                <div>
                  <dt>class</dt>
                  <dd className="mono">
                    {run.environment_manifest.environment_class}
                  </dd>
                </div>
                <div>
                  <dt>git_sha</dt>
                  <dd className="mono">
                    {run.environment_manifest.git_sha ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>python</dt>
                  <dd className="mono">
                    {run.environment_manifest.python_version ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>platform</dt>
                  <dd className="mono">
                    {run.environment_manifest.platform ?? "—"}
                  </dd>
                </div>
                <div>
                  <dt>compose</dt>
                  <dd className="mono">
                    {run.environment_manifest.compose_project ?? "—"}
                  </dd>
                </div>
              </dl>
            ) : (
              <p className="lede">No manifest pinned on this run.</p>
            )}
          </section>

          <section className="eval-panel" aria-label="Evaluation family">
            <h2>Evaluation family</h2>
            <p className="lede">
              Dual-stage pins (operational @ RESOLVED, postmortem @ CLOSED).
              Count: {family?.count ?? 0}.
            </p>

            {opsEval ? (
              <div className="eval-score-card">
                <h3>Operational</h3>
                <p>
                  <span
                    className={
                      opsEval.passed ? "pill pill-ok" : "pill pill-danger"
                    }
                  >
                    {opsEval.passed ? "passed" : "miss"}
                  </span>{" "}
                  score{" "}
                  <span className="mono">
                    {opsEval.score === null ? "—" : opsEval.score.toFixed(3)}
                  </span>{" "}
                  / threshold {opsEval.threshold}
                </p>
                <p className="mono muted-id">
                  pin rev {opsEval.pinned_incident_revision} · engine{" "}
                  {opsEval.metric_engine_version}
                </p>
                {opsEval.ground_truth_id ? (
                  <p>
                    GT{" "}
                    <Link
                      href={`/eval/ground-truth?scenario_key=${encodeURIComponent(opsEval.scenario_key)}`}
                      className="mono-link"
                    >
                      {opsEval.scenario_key} v{opsEval.ground_truth_version}
                    </Link>{" "}
                    (evaluator-only)
                  </p>
                ) : null}
              </div>
            ) : (
              <p className="lede">No operational pin yet.</p>
            )}

            {pmEval ? (
              <div className="eval-score-card">
                <h3>Postmortem</h3>
                <p>
                  <span
                    className={
                      pmEval.passed ? "pill pill-ok" : "pill pill-danger"
                    }
                  >
                    {pmEval.passed ? "passed" : "miss"}
                  </span>{" "}
                  score{" "}
                  <span className="mono">
                    {pmEval.score === null ? "—" : pmEval.score.toFixed(3)}
                  </span>{" "}
                  / threshold {pmEval.threshold}
                </p>
                <p className="mono muted-id">
                  pin rev {pmEval.pinned_incident_revision} · engine{" "}
                  {pmEval.metric_engine_version}
                </p>
              </div>
            ) : (
              <p className="lede">No postmortem pin yet.</p>
            )}
          </section>

          <section className="eval-panel" aria-label="Linked ops incident">
            <h2>Linked ops incident (live SoR)</h2>
            <p className="lede">
              Optional reference into the control-plane incident. That page is
              live ops — it must not expose GroundTruth.
            </p>
            {linkedIncidentId ? (
              <p>
                <Link
                  href={`/incidents/${linkedIncidentId}`}
                  className="mono-link"
                >
                  Open ops incident {linkedIncidentId.slice(0, 8)}…
                </Link>
              </p>
            ) : (
              <p className="lede">No incident linked on pins yet.</p>
            )}
          </section>

          {Object.keys(run.evaluation_summary || {}).length > 0 ? (
            <section className="eval-panel" aria-label="Evaluation summary">
              <h2>evaluation_summary</h2>
              <pre className="eval-json">
                {JSON.stringify(run.evaluation_summary, null, 2)}
              </pre>
            </section>
          ) : null}
        </>
      ) : null}
    </AppShell>
  );
}
