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
