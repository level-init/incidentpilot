"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

import {
  createHumanObservation,
  listEvidence,
  listHypotheses,
  provenanceBadges,
  type Evidence,
  type Hypothesis,
} from "@/lib/api";
import { useSession } from "@/lib/session";

type Props = {
  incidentId: string;
};

export function EvidenceHypothesesPanes({ incidentId }: Props) {
  const session = useSession();
  const canObserve = session.role === "responder" || session.role === "admin";
  const [evidence, setEvidence] = useState<Evidence[] | null>(null);
  const [hypotheses, setHypotheses] = useState<Hypothesis[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focusEvidenceId, setFocusEvidenceId] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  async function reload() {
    setError(null);
    const [ev, hy] = await Promise.all([
      listEvidence(incidentId),
      listHypotheses(incidentId),
    ]);
    setEvidence(ev);
    setHypotheses(hy);
  }

  useEffect(() => {
    let cancelled = false;
    listEvidence(incidentId)
      .then(async (ev) => {
        const hy = await listHypotheses(incidentId);
        if (cancelled) return;
        setEvidence(ev);
        setHypotheses(hy);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "failed to load panes");
        setEvidence([]);
        setHypotheses([]);
      });
    return () => {
      cancelled = true;
    };
  }, [incidentId]);

  const evidenceById = useMemo(() => {
    const map = new Map<string, Evidence>();
    for (const row of evidence ?? []) map.set(row.id, row);
    return map;
  }, [evidence]);

  async function onSubmitObservation(event: FormEvent) {
    event.preventDefault();
    if (!note.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createHumanObservation(incidentId, note.trim());
      setNote("");
      await reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "observation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="fact-panes">
      {error ? <p className="login-error">{error}</p> : null}

      <section className="pane pane-evidence" aria-label="Evidence">
        <header className="pane-head">
          <div>
            <p className="pane-kicker">Facts · production observations</p>
            <h2>Evidence</h2>
          </div>
          <span className="pane-count">{evidence?.length ?? "…"}</span>
        </header>

        {canObserve ? (
          <form className="observe-form" onSubmit={onSubmitObservation}>
            <label htmlFor="human-note">Add HUMAN_OBSERVATION</label>
            <textarea
              id="human-note"
              rows={3}
              value={note}
              placeholder="Responder note — stamped as human_note, not absolute truth"
              onChange={(e) => setNote(e.target.value)}
            />
            <button
              type="submit"
              className="btn-primary observe-submit"
              disabled={busy || !note.trim()}
            >
              {busy ? "Saving…" : "Post observation"}
            </button>
          </form>
        ) : (
          <p className="pane-hint">
            Viewer role is read-only — Responder+ can add HUMAN_OBSERVATION.
          </p>
        )}

        {evidence === null ? (
          <p>Loading evidence…</p>
        ) : evidence.length === 0 ? (
          <p className="lede">No evidence yet.</p>
        ) : (
          <ul className="pane-list">
            {evidence.map((row) => {
              const badges = provenanceBadges(row.provenance, {
                kind: row.kind,
                producer: row.producer,
              });
              return (
                <li
                  key={row.id}
                  id={`evidence-${row.id}`}
                  className={
                    focusEvidenceId === row.id ? "pane-item focus" : "pane-item"
                  }
                >
                  <div className="pane-item-top">
                    <span className="mono-link">{row.evidence_key}</span>
                    <time className="mono" dateTime={row.observed_at}>
                      {new Date(row.observed_at).toLocaleString()}
                    </time>
                  </div>
                  <p>{row.summary}</p>
                  <div className="badge-row">
                    {badges.map((b) => (
                      <span key={`${row.id}-${b.label}`} className="chip">
                        {b.label}: {b.value}
                      </span>
                    ))}
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </section>

      <section className="pane pane-hypotheses" aria-label="Hypotheses">
        <header className="pane-head">
          <div>
            <p className="pane-kicker">Interpretations · not facts</p>
            <h2>Hypotheses</h2>
          </div>
          <span className="pane-count">{hypotheses?.length ?? "…"}</span>
        </header>

        {hypotheses === null ? (
          <p>Loading hypotheses…</p>
        ) : hypotheses.length === 0 ? (
          <p className="lede">No hypotheses yet.</p>
        ) : (
          <ul className="pane-list">
            {hypotheses.map((row) => {
              const badges = provenanceBadges(row.provenance, {
                status: row.status,
                proposed_by: row.proposed_by,
                score_kind: row.score_kind,
              });
              return (
                <li key={row.id} className="pane-item">
                  <div className="pane-item-top">
                    <span className="pill">{row.status}</span>
                    {row.rank != null ? (
                      <span className="mono">rank {row.rank}</span>
                    ) : null}
                    {row.confidence != null ? (
                      <span className="mono">
                        score {row.confidence.toFixed(2)}
                      </span>
                    ) : null}
                  </div>
                  <p className="hypothesis-statement">{row.statement}</p>
                  <div className="badge-row">
                    {badges.map((b) => (
                      <span
                        key={`${row.id}-${b.label}`}
                        className="chip chip-interp"
                      >
                        {b.label}: {b.value}
                      </span>
                    ))}
                  </div>
                  {row.cited_evidence_ids.length ? (
                    <div className="citations">
                      <span className="metric-label">Citations</span>
                      <ul>
                        {row.cited_evidence_ids.map((eid) => {
                          const cited = evidenceById.get(eid);
                          return (
                            <li key={eid}>
                              <a
                                href={`#evidence-${eid}`}
                                className="mono-link"
                                onClick={() => setFocusEvidenceId(eid)}
                              >
                                {cited?.evidence_key ?? eid.slice(0, 8)}
                              </a>
                            </li>
                          );
                        })}
                      </ul>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ul>
        )}
      </section>
    </div>
  );
}
