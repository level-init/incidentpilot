/** Eval-only API client + outcome labels (N17). Separate from live ops. */

import { apiBase, getStoredToken } from "@/lib/auth";

export type EnvironmentManifest = {
  id: string;
  environment_class: string;
  git_sha: string | null;
  git_dirty: boolean | null;
  python_version: string | null;
  platform: string | null;
  compose_project: string | null;
  image_digests: Record<string, unknown>;
  helm_chart_hash: string | null;
  terraform_revision: string | null;
  cloud_env_id: string | null;
  extras: Record<string, unknown>;
  captured_at: string | null;
};

export type ScenarioRun = {
  id: string;
  scenario_key: string;
  status: string;
  passed: boolean | null;
  outcome: string;
  failure_kind: string | null;
  failure_detail: string | null;
  baseline_ok: boolean | null;
  evaluation_summary: Record<string, unknown>;
  injector_id: string | null;
  environment_manifest_id: string | null;
  environment_manifest: EnvironmentManifest | null;
  started_at: string | null;
  finished_at: string | null;
  evaluated_at: string | null;
  reset_at: string | null;
};

export type OperationalEvaluation = {
  id: string;
  scenario_run_id: string;
  incident_id: string;
  pinned_incident_revision: number;
  environment_manifest_id: string | null;
  ground_truth_id: string | null;
  ground_truth_version: number | null;
  scenario_key: string;
  passed: boolean;
  score: number | null;
  hard_fail: boolean;
  threshold: number;
  metrics_payload: Record<string, unknown>[];
  summary: Record<string, unknown>;
  metric_engine_version: string;
  created_at: string | null;
  idempotent_hit: boolean;
};

export type PostmortemEvaluation = {
  id: string;
  scenario_run_id: string;
  operational_evaluation_id: string;
  incident_id: string;
  postmortem_id: string;
  pinned_incident_revision: number;
  environment_manifest_id: string | null;
  ground_truth_id: string | null;
  scenario_key: string;
  passed: boolean;
  score: number | null;
  hard_fail: boolean;
  threshold: number;
  metrics_payload: Record<string, unknown>[];
  summary: Record<string, unknown>;
  metric_engine_version: string;
  created_at: string | null;
  idempotent_hit: boolean;
};

export type EvaluationFamily = {
  scenario_run_id: string;
  operational_evaluation: Record<string, unknown> | null;
  postmortem_evaluation: Record<string, unknown> | null;
  count: number;
};

export type GroundTruth = {
  id: string;
  scenario_key: string;
  version: number;
  title: string;
  origin_service_keys: string[];
  expected_hypothesis_class: string | null;
  expected_action_types: string[];
  expected_severity: string | null;
  match_spec: Record<string, unknown>;
  answer_payload: Record<string, unknown>;
  notes: string;
  created_at: string;
  updated_at: string | null;
};

/** Product taxonomy for ScenarioRun display (N3 / N17). */
export type RunOutcomeKind =
  | "in_progress"
  | "invalid_run"
  | "scored_pass"
  | "scored_fail"
  | "other";

export type RunOutcomeLabel = {
  kind: RunOutcomeKind;
  /** Short badge text */
  badge: string;
  /** One-line headline */
  headline: string;
  /** Explains FAILED ≠ scored miss */
  detail: string;
  /** Immutable snapshot once terminal */
  isImmutableSnapshot: boolean;
};

export function classifyScenarioRun(run: {
  status: string;
  passed: boolean | null;
  outcome: string;
}): RunOutcomeLabel {
  const status = run.status.toUpperCase();
  if (status === "FAILED") {
    return {
      kind: "invalid_run",
      badge: "INVALID RUN",
      headline: "FAILED — invalid run (not a scored miss)",
      detail:
        "Baseline/env/infra failed. passed stays null. This is not EVALUATED with passed=false.",
      isImmutableSnapshot: true,
    };
  }
  if (status === "EVALUATED") {
    if (run.passed === true) {
      return {
        kind: "scored_pass",
        badge: "SCORED PASS",
        headline: "EVALUATED — scored pass (passed=true)",
        detail: "Environment was valid; dual-stage score pinned as a pass.",
        isImmutableSnapshot: true,
      };
    }
    if (run.passed === false) {
      return {
        kind: "scored_fail",
        badge: "SCORED MISS",
        headline: "EVALUATED — scored miss (passed=false)",
        detail:
          "Environment was valid; the agent missed the score. Distinct from status=FAILED.",
        isImmutableSnapshot: true,
      };
    }
  }
  if (
    status === "PENDING" ||
    status === "BASELINE_PASSED" ||
    status === "FAULT_INJECTED"
  ) {
    return {
      kind: "in_progress",
      badge: "IN PROGRESS",
      headline: `${status} — run in progress`,
      detail: "Not yet FAILED or EVALUATED.",
      isImmutableSnapshot: false,
    };
  }
  return {
    kind: "other",
    badge: status || run.outcome || "UNKNOWN",
    headline: `${status || "unknown"} (${run.outcome || "—"})`,
    detail: "See status / outcome fields.",
    isImmutableSnapshot: false,
  };
}

async function evalFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const token = getStoredToken();
  if (!token) {
    throw new Error("not signed in");
  }
  const headers = new Headers(init.headers);
  headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  return fetch(`${apiBase()}${path}`, { ...init, headers });
}

export async function listScenarioRuns(opts: {
  status?: string;
  limit?: number;
} = {}): Promise<ScenarioRun[]> {
  const qs = new URLSearchParams();
  if (opts.status) qs.set("status", opts.status);
  if (opts.limit) qs.set("limit", String(opts.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await evalFetch(`/eval/scenario-runs${suffix}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `scenario-runs failed (${res.status})`);
  }
  return (await res.json()) as ScenarioRun[];
}

export async function getScenarioRun(runId: string): Promise<ScenarioRun> {
  const res = await evalFetch(`/eval/scenario-runs/${encodeURIComponent(runId)}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `scenario-run failed (${res.status})`);
  }
  return (await res.json()) as ScenarioRun;
}

export async function getEvaluationFamily(
  runId: string,
): Promise<EvaluationFamily> {
  const res = await evalFetch(
    `/eval/scenario-runs/${encodeURIComponent(runId)}/evaluation-family`,
  );
  if (!res.ok) {
    throw new Error(
      (await res.text()) || `evaluation-family failed (${res.status})`,
    );
  }
  return (await res.json()) as EvaluationFamily;
}

export async function getOperationalEvaluationForRun(
  runId: string,
): Promise<OperationalEvaluation | null> {
  const res = await evalFetch(
    `/eval/scenario-runs/${encodeURIComponent(runId)}/operational-evaluation`,
  );
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(
      (await res.text()) || `operational-evaluation failed (${res.status})`,
    );
  }
  return (await res.json()) as OperationalEvaluation;
}

export async function getPostmortemEvaluationForRun(
  runId: string,
): Promise<PostmortemEvaluation | null> {
  const res = await evalFetch(
    `/eval/scenario-runs/${encodeURIComponent(runId)}/postmortem-evaluation`,
  );
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error(
      (await res.text()) || `postmortem-evaluation failed (${res.status})`,
    );
  }
  return (await res.json()) as PostmortemEvaluation;
}

export async function listGroundTruth(
  scenarioKey?: string,
): Promise<GroundTruth[]> {
  const qs = new URLSearchParams();
  if (scenarioKey) qs.set("scenario_key", scenarioKey);
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await evalFetch(`/eval/ground-truth${suffix}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `ground-truth failed (${res.status})`);
  }
  return (await res.json()) as GroundTruth[];
}
