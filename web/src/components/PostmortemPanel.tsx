"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createPostmortemDraft,
  exportPostmortem,
  finalizePostmortem,
  getPostmortem,
  type Postmortem,
} from "@/lib/api";
import { useSession } from "@/lib/session";

type Props = {
  incidentId: string;
  incidentState: string;
  onChanged?: () => void;
};

export function PostmortemPanel({
  incidentId,
  incidentState,
  onChanged,
}: Props) {
  const session = useSession();
  const canWrite =
    session.role === "responder" || session.role === "admin";
  const [pm, setPm] = useState<Postmortem | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [actionTitle, setActionTitle] = useState("");
  const [actionOwner, setActionOwner] = useState("");
  const [exportJson, setExportJson] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPm(await getPostmortem(incidentId));
    } catch (err: unknown) {
      setPm(null);
      setError(err instanceof Error ? err.message : "postmortem load failed");
    }
  }, [incidentId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onDraft() {
    setBusy(true);
    setError(null);
    try {
      await createPostmortemDraft(incidentId, {});
      await load();
      onChanged?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "draft failed");
    } finally {
      setBusy(false);
    }
  }

  async function onFinalize(event: FormEvent) {
    event.preventDefault();
    if (!actionTitle.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await finalizePostmortem(incidentId, [
        {
          title: actionTitle.trim(),
          owner: actionOwner.trim() || undefined,
        },
      ]);
      setActionTitle("");
      setActionOwner("");
      await load();
      onChanged?.();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "finalize failed");
    } finally {
      setBusy(false);
    }
  }

  async function onExport() {
    setBusy(true);
    setError(null);
    try {
      const pkg = await exportPostmortem(incidentId);
      setExportJson(JSON.stringify(pkg, null, 2));
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "export failed");
    } finally {
      setBusy(false);
    }
  }

  if (pm === undefined) {
    return (
      <section className="record-panel" aria-label="Postmortem">
        <p>Loading postmortem…</p>
      </section>
    );
  }

  const draftEligible = incidentState === "RESOLVED" && (pm === null || pm.status === "DRAFT");
  const finalizeEligible = pm?.status === "DRAFT";
  const exportEligible = pm?.status === "FINAL";

  return (
    <section className="record-panel" aria-label="Postmortem">
      <header className="timeline-head">
        <div>
          <h2>Postmortem</h2>
          <span className="metric-label">human-readable record · L4–L6</span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {error ? <p className="login-error">{error}</p> : null}

      {pm === null ? (
        <p className="lede">
          No postmortem yet
          {incidentState === "RESOLVED"
            ? " — draft after RESOLVED."
            : ` (state ${incidentState}).`}
        </p>
      ) : (
        <>
          <dl className="detail-grid">
            <div>
              <dt>Status</dt>
              <dd>
                <span className="pill">{pm.status}</span>
              </dd>
            </div>
            <div>
              <dt>Title</dt>
              <dd>{pm.title}</dd>
            </div>
          </dl>
          {pm.body_markdown ? (
            <pre className="scope-json postmortem-body">{pm.body_markdown}</pre>
          ) : null}
          {pm.corrective_actions.length > 0 ? (
            <div>
              <p className="metric-label">Corrective actions</p>
              <ul className="admin-version-list">
                {pm.corrective_actions.map((a, i) => (
                  <li key={i} className="mono">
                    {JSON.stringify(a)}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </>
      )}

      {canWrite ? (
        <div className="record-actions">
          {draftEligible ? (
            <button
              type="button"
              className="btn-primary"
              disabled={busy}
              onClick={() => void onDraft()}
            >
              {pm?.status === "DRAFT" ? "Refresh draft" : "Create draft"}
            </button>
          ) : null}

          {finalizeEligible ? (
            <form className="observe-form" onSubmit={onFinalize}>
              <h3>Finalize</h3>
              <label htmlFor="ca-title">Corrective action title</label>
              <input
                id="ca-title"
                value={actionTitle}
                onChange={(e) => setActionTitle(e.target.value)}
                required
              />
              <label htmlFor="ca-owner">Owner (optional)</label>
              <input
                id="ca-owner"
                value={actionOwner}
                onChange={(e) => setActionOwner(e.target.value)}
              />
              <button
                type="submit"
                className="btn-primary"
                disabled={busy || !actionTitle.trim()}
              >
                Finalize → FINAL
              </button>
            </form>
          ) : null}
        </div>
      ) : (
        <p className="pane-hint">Viewer: read-only postmortem.</p>
      )}

      {exportEligible ? (
        <button
          type="button"
          className="btn-ghost"
          disabled={busy}
          onClick={() => void onExport()}
        >
          Export package
        </button>
      ) : null}

      {exportJson ? (
        <pre className="scope-json">{exportJson}</pre>
      ) : null}
    </section>
  );
}
