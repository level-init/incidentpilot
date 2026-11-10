"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppShell } from "@/components/AppShell";
import {
  formatDuration,
  getIncident,
  listTimeline,
  type Incident,
  type TimelineEvent,
} from "@/lib/api";

export default function IncidentDetailPage() {
  const params = useParams<{ id: string }>();
  const ref = params?.id ?? "";
  const [incident, setIncident] = useState<Incident | null>(null);
  const [timeline, setTimeline] = useState<TimelineEvent[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [nowMs, setNowMs] = useState(() => Date.now());

  const load = useCallback(async () => {
    if (!ref) return;
    setError(null);
    try {
      const inc = await getIncident(ref);
      setIncident(inc);
      const events = await listTimeline(inc.id, "asc");
      setTimeline(events);
      setNowMs(Date.now());
    } catch (err: unknown) {
      setIncident(null);
      setTimeline(null);
      setError(err instanceof Error ? err.message : "failed to load");
    }
  }, [ref]);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <AppShell>
      <p className="detail-back">
        <Link href="/incidents" className="mono-link">
          ← Incidents
        </Link>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </p>

      {error ? <p className="login-error">{error}</p> : null}

      {!incident && !error ? <p>Loading incident…</p> : null}

      {incident ? (
        <>
          <header className="detail-header" aria-label="Incident header">
            <div className="detail-title-row">
              <h1>{incident.title}</h1>
              <span className="pill pill-state">{incident.state}</span>
            </div>
            <dl className="detail-meta">
              <div>
                <dt>Incident ID</dt>
                <dd className="mono">{incident.public_id}</dd>
              </div>
              <div>
                <dt>UUID</dt>
                <dd className="mono">{incident.id}</dd>
              </div>
              <div>
                <dt>State</dt>
                <dd>
                  <span className="pill pill-state">{incident.state}</span>
                </dd>
              </div>
              <div>
                <dt>Severity</dt>
                <dd>
                  <span className="pill">{incident.severity ?? "—"}</span>
                </dd>
              </div>
              <div>
                <dt>Env</dt>
                <dd className="mono">
                  {incident.environments.length
                    ? incident.environments.join(", ")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Service</dt>
                <dd className="mono">
                  {incident.service_keys.length
                    ? incident.service_keys.join(", ")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Duration</dt>
                <dd className="mono">
                  {formatDuration(
                    incident.opened_at,
                    incident.resolved_at,
                    incident.closed_at,
                    nowMs,
                  )}
                </dd>
              </div>
              <div>
                <dt>Revision</dt>
                <dd className="mono">r{incident.incident_revision}</dd>
              </div>
            </dl>
            {incident.summary ? (
              <p className="detail-summary">{incident.summary}</p>
            ) : null}
          </header>

          <section className="timeline-pane" aria-label="Timeline">
            <div className="timeline-head">
              <h2>Timeline</h2>
              <span className="metric-label">process chronicle · oldest first</span>
            </div>
            {timeline === null ? (
              <p>Loading timeline…</p>
            ) : timeline.length === 0 ? (
              <p className="lede">No timeline events yet.</p>
            ) : (
              <ol className="timeline-list">
                {timeline.map((ev) => (
                  <li key={ev.id}>
                    <time dateTime={ev.occurred_at} className="mono">
                      {new Date(ev.occurred_at).toLocaleString()}
                    </time>
                    <span className="chip">{ev.event_type}</span>
                    <p>{ev.summary}</p>
                    <span className="timeline-actor mono">{ev.actor}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </>
      ) : null}
    </AppShell>
  );
}
