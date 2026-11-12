"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  createAdminRunbook,
  createAdminRunbookVersion,
  listAdminRunbooks,
  publishAdminRunbookVersion,
  type AdminRunbook,
} from "@/lib/api";

export function AdminRunbooksPanel() {
  const [rows, setRows] = useState<AdminRunbook[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState("");
  const [title, setTitle] = useState("");
  const [serviceKey, setServiceKey] = useState("");
  const [draftRb, setDraftRb] = useState("");
  const [actions, setActions] = useState("ROLLBACK_DEPLOYMENT");
  const [prose, setProse] = useState("# steps\n");

  const load = useCallback(async () => {
    setError(null);
    try {
      const data = await listAdminRunbooks();
      setRows(data);
      setDraftRb((prev) => {
        if (prev && data.some((r) => r.runbook_id === prev)) return prev;
        return data[0]?.runbook_id ?? "";
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "runbooks load failed");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function onCreate(event: FormEvent) {
    event.preventDefault();
    if (!key.trim() || !title.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const created = await createAdminRunbook({
        key: key.trim(),
        title: title.trim(),
        service_key: serviceKey.trim() || undefined,
      });
      setKey("");
      setTitle("");
      setServiceKey("");
      setDraftRb(created.runbook_id);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "create failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDraftVersion(event: FormEvent) {
    event.preventDefault();
    if (!draftRb) return;
    const allowed = actions
      .split(",")
      .map((a) => a.trim())
      .filter(Boolean);
    if (allowed.length === 0) {
      setError("allowed_action_types required (authority)");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await createAdminRunbookVersion(draftRb, {
        body_markdown: prose,
        allowed_action_types: allowed,
      });
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "draft failed");
    } finally {
      setBusy(false);
    }
  }

  async function onPublish(versionId: string) {
    setBusy(true);
    setError(null);
    try {
      await publishAdminRunbookVersion(versionId);
      await load();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "publish failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-section" aria-label="Runbooks">
      <header className="timeline-head">
        <div>
          <h2>Runbooks</h2>
          <span className="metric-label">
            publish · authority = allowed_action_types
          </span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void load()}>
          Refresh
        </button>
      </header>

      {error ? <p className="login-error">{error}</p> : null}

      <div className="table-wrap">
        <table className="incident-table">
          <thead>
            <tr>
              <th>Key</th>
              <th>Title</th>
              <th>Active</th>
              <th>Authority</th>
              <th>Versions</th>
            </tr>
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={5}>No runbooks yet.</td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr key={r.runbook_id}>
                  <td className="mono">{r.key}</td>
                  <td>{r.title}</td>
                  <td className="mono">
                    {r.active_version != null ? `v${r.active_version}` : "—"}
                  </td>
                  <td className="mono">
                    {r.active_allowed_action_types.join(", ") || "—"}
                  </td>
                  <td>
                    <ul className="admin-version-list">
                      {r.versions.map((v) => (
                        <li key={v.runbook_version_id}>
                          <span className="mono">
                            v{v.version} · {v.status}
                          </span>{" "}
                          {v.status === "draft" ? (
                            <button
                              type="button"
                              className="btn-ghost"
                              disabled={busy}
                              onClick={() => void onPublish(v.runbook_version_id)}
                            >
                              Publish
                            </button>
                          ) : null}
                        </li>
                      ))}
                    </ul>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <form className="observe-form admin-form" onSubmit={onCreate}>
        <h3>Create runbook</h3>
        <label htmlFor="rb-key">Key</label>
        <input
          id="rb-key"
          className="mono"
          value={key}
          onChange={(e) => setKey(e.target.value)}
          required
        />
        <label htmlFor="rb-title">Title</label>
        <input
          id="rb-title"
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          required
        />
        <label htmlFor="rb-svc">Service key (optional)</label>
        <input
          id="rb-svc"
          className="mono"
          value={serviceKey}
          onChange={(e) => setServiceKey(e.target.value)}
        />
        <button type="submit" className="btn-primary" disabled={busy}>
          Create
        </button>
      </form>

      <form className="observe-form admin-form" onSubmit={onDraftVersion}>
        <h3>Draft version</h3>
        <label htmlFor="rb-pick">Runbook</label>
        <select
          id="rb-pick"
          value={draftRb}
          onChange={(e) => setDraftRb(e.target.value)}
        >
          {rows.map((r) => (
            <option key={r.runbook_id} value={r.runbook_id}>
              {r.key}
            </option>
          ))}
        </select>
        <label htmlFor="rb-actions">
          Allowed action types (authority, comma-separated)
        </label>
        <input
          id="rb-actions"
          className="mono"
          value={actions}
          onChange={(e) => setActions(e.target.value)}
          required
        />
        <label htmlFor="rb-prose">Body markdown (untrusted prose)</label>
        <textarea
          id="rb-prose"
          rows={4}
          value={prose}
          onChange={(e) => setProse(e.target.value)}
        />
        <button
          type="submit"
          className="btn-primary"
          disabled={busy || !draftRb}
        >
          Add draft
        </button>
      </form>
    </section>
  );
}
