"use client";

import { FormEvent, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";

import {
  STUB_PERSONAS,
  fetchSession,
  setStoredToken,
} from "@/lib/auth";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const next = useMemo(() => params.get("next") || "/incidents", [params]);
  const [token, setToken] = useState(STUB_PERSONAS[0].token);
  const [custom, setCustom] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await fetchSession(token.trim());
      setStoredToken(token.trim());
      router.replace(next.startsWith("/") ? next : "/incidents");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Login failed");
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <form className="login-card" onSubmit={onSubmit}>
        <span className="brand-mark">IncidentPilot</span>
        <p className="lede">
          Sign in with a local stub session. Actor identity comes from the API —
          never from the browser body.
        </p>

        {error ? <p className="login-error">{error}</p> : null}

        <label htmlFor="persona">Session</label>
        {!custom ? (
          <select
            id="persona"
            value={token}
            onChange={(e) => {
              if (e.target.value === "__custom") {
                setCustom(true);
                setToken("");
                return;
              }
              setToken(e.target.value);
            }}
          >
            {STUB_PERSONAS.map((p) => (
              <option key={p.token} value={p.token}>
                {p.label} ({p.token})
              </option>
            ))}
            <option value="__custom">Custom bearer token…</option>
          </select>
        ) : (
          <input
            id="persona"
            autoFocus
            placeholder="Bearer token"
            value={token}
            onChange={(e) => setToken(e.target.value)}
          />
        )}

        <button className="btn-primary" type="submit" disabled={busy || !token}>
          {busy ? "Checking session…" : "Continue"}
        </button>

        <p className="hint">
          Uses <code>GET /auth/me</code> with{" "}
          <code>Authorization: Bearer …</code>. Admin nav for{" "}
          <code>local-dev-admin</code>; Eval nav for{" "}
          <code>local-dev-evaluator</code> only.
        </p>
      </form>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="login-page">Loading…</div>}>
      <LoginForm />
    </Suspense>
  );
}
