"use client";

import { FormEvent, useCallback, useEffect, useState } from "react";

import {
  activatePolicyVersion,
  listAdminPolicies,
  listPolicyVersions,
  publishPolicyVersion,
  type PolicyKey,
  type PolicyVersion,
} from "@/lib/api";

export function AdminPoliciesPanel() {
  const [keys, setKeys] = useState<PolicyKey[]>([]);
  const [selected, setSelected] = useState("default");
  const [versions, setVersions] = useState<PolicyVersion[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState("");
  const [bodyJson, setBodyJson] = useState('{\n  "rules": []\n}');
  const [activateOnPublish, setActivateOnPublish] = useState(true);

  const loadKeys = useCallback(async () => {
    setError(null);
    try {
      const policyKeys = await listAdminPolicies();
      setKeys(policyKeys);
      setSelected((prev) => {
        if (policyKeys.some((k) => k.policy_key === prev)) return prev;
        return policyKeys[0]?.policy_key ?? prev;
      });
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "policy load failed");
    }
  }, []);

  const loadVersions = useCallback(async (key: string) => {
    setError(null);
    try {
      setVersions(await listPolicyVersions(key));
    } catch (err: unknown) {
      setVersions([]);
      setError(err instanceof Error ? err.message : "versions failed");
    }
  }, []);

  useEffect(() => {
    void loadKeys();
  }, [loadKeys]);

  useEffect(() => {
    void loadVersions(selected);
  }, [loadVersions, selected]);

  async function refresh() {
    await loadKeys();
    await loadVersions(selected);
  }

  async function onPublish(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body = JSON.parse(bodyJson) as Record<string, unknown>;
      await publishPolicyVersion(selected, {
        body,
        notes: notes.trim() || undefined,
        activate: activateOnPublish,
      });
      setNotes("");
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "publish failed");
    } finally {
      setBusy(false);
    }
  }

  async function onActivate(version: number) {
    setBusy(true);
    setError(null);
    try {
      await activatePolicyVersion(selected, version);
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "activate failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="admin-section" aria-label="Policies">
      <header className="timeline-head">
        <div>
          <h2>Policies</h2>
          <span className="metric-label">version history · admin:config</span>
        </div>
        <button type="button" className="btn-ghost" onClick={() => void refresh()}>
          Refresh
        </button>
      </header>

      {error ? <p className="login-error">{error}</p> : null}

      <div className="filters">
        <label htmlFor="policy-key">
          Policy key
          <select
            id="policy-key"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {(keys.length ? keys : [{ policy_key: selected } as PolicyKey]).map(
              (k) => (
                <option key={k.policy_key} value={k.policy_key}>
                  {k.policy_key}
                  {"version_count" in k && k.version_count
                    ? ` (${k.version_count} vers.)`
                    : ""}
                </option>
              ),
            )}
          </select>
        </label>
      </div>

      <div className="table-wrap">
        <table className="incident-table">
          <thead>
            <tr>
              <th>Version</th>
              <th>Active</th>
              <th>Created by</th>
              <th>Notes</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {versions.length === 0 ? (
              <tr>
                <td colSpan={5}>No versions yet.</td>
              </tr>
            ) : (
              versions.map((v) => (
                <tr key={v.policy_definition_id}>
                  <td className="mono">{v.version_label}</td>
                  <td>{v.active ? <span className="pill">active</span> : "—"}</td>
                  <td className="mono">{v.created_by}</td>
                  <td>{v.notes ?? "—"}</td>
                  <td>
                    {!v.active ? (
                      <button
                        type="button"
                        className="btn-ghost"
                        disabled={busy}
                        onClick={() => void onActivate(v.version)}
                      >
                        Activate
                      </button>
                    ) : null}
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <form className="observe-form admin-form" onSubmit={onPublish}>
        <h3>Publish new version</h3>
        <label htmlFor="policy-body">Body JSON</label>
        <textarea
          id="policy-body"
          rows={6}
          className="mono"
          value={bodyJson}
          onChange={(e) => setBodyJson(e.target.value)}
        />
        <label htmlFor="policy-notes">Notes</label>
        <input
          id="policy-notes"
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="why this version"
        />
        <label className="check-row">
          <input
            type="checkbox"
            checked={activateOnPublish}
            onChange={(e) => setActivateOnPublish(e.target.checked)}
          />
          Activate on publish
        </label>
        <button type="submit" className="btn-primary" disabled={busy}>
          {busy ? "Publishing…" : "Publish"}
        </button>
      </form>
    </section>
  );
}
