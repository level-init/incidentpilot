import { apiBase, getStoredToken } from "@/lib/auth";

export type Incident = {
  id: string;
  public_id: string;
  state: string;
  title: string;
  severity: string | null;
  incident_revision: number;
  summary: string | null;
  opened_at: string;
  resolved_at: string | null;
  closed_at: string | null;
  service_keys: string[];
  environments: string[];
};

export type TimelineEvent = {
  id: string;
  incident_id: string;
  event_type: string;
  summary: string;
  actor: string;
  occurred_at: string;
  payload: Record<string, unknown>;
};

export type Evidence = {
  id: string;
  evidence_key: string;
  incident_id: string;
  kind: string;
  summary: string;
  fingerprint: string;
  observed_at: string;
  producer: string;
  provenance: Record<string, unknown>;
};

export type Hypothesis = {
  id: string;
  incident_id: string;
  status: string;
  statement: string;
  proposed_by: string;
  confidence: number | null;
  rank: number | null;
  score_kind: string;
  provenance: Record<string, unknown>;
  cited_evidence_ids: string[];
};

export type IncidentListFilters = {
  state?: string;
  severity?: string;
  service?: string;
};

async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
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

/** HTTP error with status — used for stale concurrency handling (M10). */
export class ApiError extends Error {
  status: number;
  body: string;

  constructor(status: number, body: string, fallback: string) {
    super(body || fallback);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }

  get isStale(): boolean {
    return (
      this.status === 409 &&
      (/STALE_ACTION_VERSION/i.test(this.body) ||
        /stale revision/i.test(this.body))
    );
  }
}

export async function listIncidents(
  filters: IncidentListFilters = {},
): Promise<Incident[]> {
  const qs = new URLSearchParams();
  if (filters.state) qs.set("state", filters.state);
  if (filters.severity) qs.set("severity", filters.severity);
  if (filters.service) qs.set("service", filters.service);
  const suffix = qs.toString() ? `?${qs}` : "";
  const res = await apiFetch(`/incidents${suffix}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `list failed (${res.status})`);
  }
  return (await res.json()) as Incident[];
}

export async function getIncident(ref: string): Promise<Incident> {
  const res = await apiFetch(`/incidents/${encodeURIComponent(ref)}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `incident failed (${res.status})`);
  }
  return (await res.json()) as Incident;
}

export async function listTimeline(
  incidentId: string,
  order: "asc" | "desc" = "asc",
): Promise<TimelineEvent[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/timeline?order=${order}`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `timeline failed (${res.status})`);
  }
  return (await res.json()) as TimelineEvent[];
}

export async function listEvidence(incidentId: string): Promise<Evidence[]> {
  const qs = new URLSearchParams({ incident_id: incidentId });
  const res = await apiFetch(`/evidence?${qs}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `evidence failed (${res.status})`);
  }
  return (await res.json()) as Evidence[];
}

export async function listHypotheses(incidentId: string): Promise<Hypothesis[]> {
  const qs = new URLSearchParams({ incident_id: incidentId });
  const res = await apiFetch(`/hypotheses?${qs}`);
  if (!res.ok) {
    throw new Error((await res.text()) || `hypotheses failed (${res.status})`);
  }
  return (await res.json()) as Hypothesis[];
}

export async function createHumanObservation(
  incidentId: string,
  summary: string,
): Promise<Evidence> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/observations`,
    {
      method: "POST",
      body: JSON.stringify({ summary }),
    },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `observation failed (${res.status})`);
  }
  return (await res.json()) as Evidence;
}

export type ImpactSnapshot = {
  id: string;
  incident_id: string;
  captured_at: string;
  severity: string | null;
  customer_impact_summary: string | null;
  estimated_affected_users: number | null;
  metrics: Record<string, unknown>;
  provenance: Record<string, unknown>;
};

export type ChangeRecord = {
  id: string;
  change_key: string;
  change_type: string;
  service_key: string | null;
  summary: string;
  source: string;
  external_ref: string | null;
  observed_at: string;
  payload: Record<string, unknown>;
};

export type PinnedRunbook = {
  pinned: boolean;
  runbook_key: string | null;
  title: string | null;
  version: number | null;
  runbook_version_id: string | null;
  allowed_action_types: string[];
  body_markdown: string | null;
  authority_note: string;
};

export async function listImpactSnapshots(
  incidentId: string,
): Promise<ImpactSnapshot[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/impact-snapshots`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `impact failed (${res.status})`);
  }
  return (await res.json()) as ImpactSnapshot[];
}

export async function listChanges(incidentId: string): Promise<ChangeRecord[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/changes`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `changes failed (${res.status})`);
  }
  return (await res.json()) as ChangeRecord[];
}

export async function getPinnedRunbook(
  incidentId: string,
): Promise<PinnedRunbook> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/runbook`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `runbook failed (${res.status})`);
  }
  return (await res.json()) as PinnedRunbook;
}

export type ResolveContext = {
  eligible: boolean;
  current_state: string;
  incident_revision: number;
  reason_required: boolean;
  message: string;
  health: {
    outcome: string | null;
    criteria: Record<string, unknown>;
    observations: Record<string, unknown>;
    decided_at: string | null;
  } | null;
};

export async function fetchResolveContext(
  incidentId: string,
): Promise<ResolveContext> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/resolve-context`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `resolve-context failed (${res.status})`);
  }
  return (await res.json()) as ResolveContext;
}

export async function manualResolve(
  incidentId: string,
  body: { reason: string; expected_revision: number },
): Promise<void> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/resolve`,
    {
      method: "POST",
      body: JSON.stringify(body),
    },
  );
  if (!res.ok) {
    throw new ApiError(
      res.status,
      await res.text(),
      `resolve failed (${res.status})`,
    );
  }
}

export type PolicyKey = {
  policy_key: string;
  version_count: number;
  latest_version: number;
  active_version: number | null;
};

export type PolicyVersion = {
  policy_definition_id: string;
  policy_key: string;
  version: number;
  version_label: string;
  body: Record<string, unknown>;
  notes: string | null;
  created_by: string;
  active: boolean;
};

export type AdminRunbookVersion = {
  runbook_version_id: string;
  runbook_id: string;
  version: number;
  status: string;
  allowed_action_types: string[];
  proposed_by: string | null;
  created_at: string | null;
};

export type AdminRunbook = {
  runbook_id: string;
  key: string;
  title: string;
  hypothesis_class: string | null;
  description: string | null;
  service_key: string | null;
  active_version_id: string | null;
  active_version: number | null;
  active_status: string | null;
  active_allowed_action_types: string[];
  versions: AdminRunbookVersion[];
};

export type IntegrationStatus = {
  key: string;
  display_name: string;
  kind: string;
  configured: boolean;
  endpoint: string | null;
  scope: Record<string, unknown>;
  secrets_exposed: boolean;
  notes: string | null;
};

export async function listAdminPolicies(): Promise<PolicyKey[]> {
  const res = await apiFetch("/admin/policies");
  if (!res.ok) {
    throw new Error((await res.text()) || `admin policies failed (${res.status})`);
  }
  return (await res.json()) as PolicyKey[];
}

export async function listPolicyVersions(
  policyKey: string,
): Promise<PolicyVersion[]> {
  const res = await apiFetch(
    `/policies/${encodeURIComponent(policyKey)}/versions`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `policy versions failed (${res.status})`);
  }
  return (await res.json()) as PolicyVersion[];
}

export async function publishPolicyVersion(
  policyKey: string,
  body: { body: Record<string, unknown>; notes?: string; activate?: boolean },
): Promise<PolicyVersion> {
  const res = await apiFetch(`/policies/${encodeURIComponent(policyKey)}/versions`, {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error((await res.text()) || `publish policy failed (${res.status})`);
  }
  return (await res.json()) as PolicyVersion;
}

export async function activatePolicyVersion(
  policyKey: string,
  version: number,
): Promise<void> {
  const res = await apiFetch(
    `/policies/${encodeURIComponent(policyKey)}/versions/${version}/activate`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `activate policy failed (${res.status})`);
  }
}

export async function listAdminRunbooks(): Promise<AdminRunbook[]> {
  const res = await apiFetch("/admin/runbooks");
  if (!res.ok) {
    throw new Error((await res.text()) || `admin runbooks failed (${res.status})`);
  }
  return (await res.json()) as AdminRunbook[];
}

export async function createAdminRunbook(body: {
  key: string;
  title: string;
  service_key?: string;
  hypothesis_class?: string;
  description?: string;
}): Promise<AdminRunbook> {
  const res = await apiFetch("/admin/runbooks", {
    method: "POST",
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    throw new Error((await res.text()) || `create runbook failed (${res.status})`);
  }
  return (await res.json()) as AdminRunbook;
}

export async function createAdminRunbookVersion(
  runbookId: string,
  body: { body_markdown: string; allowed_action_types: string[] },
): Promise<AdminRunbookVersion> {
  const res = await apiFetch(
    `/admin/runbooks/${encodeURIComponent(runbookId)}/versions`,
    { method: "POST", body: JSON.stringify(body) },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `create version failed (${res.status})`);
  }
  return (await res.json()) as AdminRunbookVersion;
}

export async function publishAdminRunbookVersion(
  runbookVersionId: string,
): Promise<AdminRunbookVersion> {
  const res = await apiFetch(
    `/admin/runbooks/versions/${encodeURIComponent(runbookVersionId)}/publish`,
    { method: "POST" },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `publish version failed (${res.status})`);
  }
  return (await res.json()) as AdminRunbookVersion;
}

export async function listAdminIntegrations(): Promise<IntegrationStatus[]> {
  const res = await apiFetch("/admin/integrations");
  if (!res.ok) {
    throw new Error(
      (await res.text()) || `admin integrations failed (${res.status})`,
    );
  }
  return (await res.json()) as IntegrationStatus[];
}

export type Postmortem = {
  id: string;
  incident_id: string;
  status: string;
  title: string;
  body_markdown: string;
  corrective_actions: Array<Record<string, unknown>>;
};

export type AuditEvent = {
  id: string;
  incident_id: string | null;
  action: string;
  actor: string;
  resource_type: string;
  resource_id: string | null;
  outcome: string;
  occurred_at: string;
  details: Record<string, unknown>;
};

export type AiInvocationSummary = {
  invocation_id: string;
  incident_id: string | null;
  purpose: string;
  provider: string;
  model: string;
  status: string;
  artifact_uri: string | null;
  created_at: string;
};

export type AiInvocationProvenance = {
  invocation_id: string;
  incident_id: string | null;
  purpose: string;
  provider: string;
  model: string;
  status: string;
  prompt_version: string | null;
  input_evidence_ids: string[];
  artifact_uri: string | null;
  request_metadata: Record<string, unknown>;
  response_metadata: Record<string, unknown>;
  error_summary: string | null;
  created_at: string;
  prompt_hash: string | null;
  response_hash: string | null;
  input_tokens: number | null;
  output_tokens: number | null;
  latency_ms: number | null;
};

export async function getPostmortem(
  incidentId: string,
): Promise<Postmortem | null> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/postmortem`,
  );
  if (res.status === 404) return null;
  if (!res.ok) {
    throw new Error((await res.text()) || `postmortem failed (${res.status})`);
  }
  return (await res.json()) as Postmortem;
}

export async function createPostmortemDraft(
  incidentId: string,
  body: Record<string, unknown> = {},
): Promise<void> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/postmortem/draft`,
    { method: "POST", body: JSON.stringify(body) },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `draft failed (${res.status})`);
  }
}

export async function finalizePostmortem(
  incidentId: string,
  corrective_actions: Array<Record<string, unknown>>,
): Promise<void> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/postmortem/finalize`,
    {
      method: "POST",
      body: JSON.stringify({ corrective_actions }),
    },
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `finalize failed (${res.status})`);
  }
}

export async function exportPostmortem(
  incidentId: string,
): Promise<Record<string, unknown>> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/postmortem/export`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `export failed (${res.status})`);
  }
  return (await res.json()) as Record<string, unknown>;
}

export async function listAudit(
  incidentId: string,
  order: "asc" | "desc" = "asc",
): Promise<AuditEvent[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/audit?order=${order}`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `audit failed (${res.status})`);
  }
  return (await res.json()) as AuditEvent[];
}

export async function listIncidentAiInvocations(
  incidentId: string,
): Promise<AiInvocationSummary[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/ai-invocations`,
  );
  if (!res.ok) {
    throw new Error(
      (await res.text()) || `ai-invocations failed (${res.status})`,
    );
  }
  return (await res.json()) as AiInvocationSummary[];
}

export async function getAiInvocationProvenance(
  invocationId: string,
): Promise<AiInvocationProvenance> {
  const res = await apiFetch(
    `/ai-invocations/${encodeURIComponent(invocationId)}/provenance`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `provenance failed (${res.status})`);
  }
  return (await res.json()) as AiInvocationProvenance;
}

export type RemediationAttempt = {
  id: string;
  action_version: number;
  attempt_number: number;
  state: string;
  error_summary: string | null;
  reconciliation_state: string | null;
  adapter_result: Record<string, unknown>;
  unsafe_to_retry: boolean;
};

export type RemediationAction = {
  action_id: string;
  action_type: string;
  status: string;
  current_version: number;
  is_reversible: boolean;
  risk: string;
  parameters: Record<string, unknown>;
  target_ref: Record<string, unknown>;
  policy: {
    decision: string;
    reason: string | null;
    policy_key: string | null;
    policy_version: string | null;
  } | null;
  approval: {
    id: string;
    action_version: number;
    status: string;
    decided_by: string | null;
  } | null;
  attempts: RemediationAttempt[];
};

export async function listRemediation(
  incidentId: string,
): Promise<RemediationAction[]> {
  const res = await apiFetch(
    `/incidents/${encodeURIComponent(incidentId)}/remediation`,
  );
  if (!res.ok) {
    throw new Error((await res.text()) || `remediation failed (${res.status})`);
  }
  return (await res.json()) as RemediationAction[];
}

export async function decideApproval(
  approvalId: string,
  status: "APPROVED" | "REJECTED",
  actionVersion: number,
): Promise<void> {
  const res = await apiFetch(
    `/approvals/${encodeURIComponent(approvalId)}/decide`,
    {
      method: "POST",
      body: JSON.stringify({ status, action_version: actionVersion }),
    },
  );
  if (!res.ok) {
    throw new ApiError(
      res.status,
      await res.text(),
      `decide failed (${res.status})`,
    );
  }
}

export function provenanceBadges(
  provenance: Record<string, unknown>,
  extras: Record<string, string | undefined> = {},
): Array<{ label: string; value: string }> {
  const badges: Array<{ label: string; value: string }> = [];
  for (const [label, value] of Object.entries(extras)) {
    if (value) badges.push({ label, value });
  }
  for (const key of [
    "layer",
    "quality",
    "truthfulness",
    "source",
    "score_kind",
    "quality_rule_id",
    "blob_status",
  ]) {
    const raw = provenance[key];
    if (raw === undefined || raw === null || raw === "") continue;
    badges.push({ label: key, value: String(raw) });
  }
  return badges;
}

/** Open duration: now − opened_at, or resolved/closed − opened_at when terminal. */
export function formatDuration(
  openedAt: string,
  resolvedAt: string | null,
  closedAt: string | null,
  nowMs: number = Date.now(),
): string {
  const start = Date.parse(openedAt);
  if (Number.isNaN(start)) return "—";
  const endRaw = closedAt ?? resolvedAt;
  const end = endRaw ? Date.parse(endRaw) : nowMs;
  const ms = Math.max(0, (Number.isNaN(end) ? nowMs : end) - start);
  const minutes = Math.floor(ms / 60_000);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  const rem = minutes % 60;
  if (hours < 48) return rem ? `${hours}h ${rem}m` : `${hours}h`;
  const days = Math.floor(hours / 24);
  const rh = hours % 24;
  return rh ? `${days}d ${rh}h` : `${days}d`;
}

const TERMINAL = new Set(["RESOLVED", "CLOSED"]);

export function overviewMetrics(incidents: Incident[]) {
  const active = incidents.filter((i) => !TERMINAL.has(i.state));
  const byState = new Map<string, number>();
  const bySeverity = new Map<string, number>();
  for (const i of active) {
    byState.set(i.state, (byState.get(i.state) ?? 0) + 1);
    const sev = i.severity ?? "unset";
    bySeverity.set(sev, (bySeverity.get(sev) ?? 0) + 1);
  }
  return {
    total: incidents.length,
    active: active.length,
    byState: [...byState.entries()].sort((a, b) => b[1] - a[1]),
    bySeverity: [...bySeverity.entries()].sort((a, b) => a[0].localeCompare(b[0])),
  };
}
