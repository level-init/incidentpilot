/** Stub Bearer session for AUTH_MODE=stub (C1). Token lives in sessionStorage. */

export type OpsRole = "viewer" | "responder" | "admin";

export type Session = {
  actor_id: string;
  role: OpsRole;
  auth_mode: string;
  email: string | null;
  eval_entitled: boolean;
};

export const TOKEN_KEY = "ip_bearer_token";

export const STUB_PERSONAS: ReadonlyArray<{
  token: string;
  label: string;
  role: OpsRole;
}> = [
  { token: "local-dev", label: "Responder", role: "responder" },
  { token: "local-dev-admin", label: "Admin", role: "admin" },
  { token: "local-dev-viewer", label: "Viewer", role: "viewer" },
];

export function apiBase(): string {
  return (
    process.env.NEXT_PUBLIC_API_BASE_URL?.replace(/\/$/, "") ||
    "http://localhost:8000"
  );
}

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return sessionStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  sessionStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  sessionStorage.removeItem(TOKEN_KEY);
}

export async function fetchSession(token: string): Promise<Session> {
  const res = await fetch(`${apiBase()}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(detail || `auth failed (${res.status})`);
  }
  return (await res.json()) as Session;
}
