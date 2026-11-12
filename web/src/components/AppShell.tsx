"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";

import {
  clearStoredToken,
  fetchSession,
  getStoredToken,
  type Session,
} from "@/lib/auth";
import { SessionProvider } from "@/lib/session";

type Props = {
  children: ReactNode;
  /** Require admin role for this page. */
  requireAdmin?: boolean;
};

const OPS_LINKS = [
  { href: "/incidents", label: "Incidents" },
  { href: "/topology", label: "Topology" },
] as const;

const ADMIN_LINKS = [
  { href: "/admin", label: "Admin" },
] as const;

export function AppShell({ children, requireAdmin = false }: Props) {
  const router = useRouter();
  const pathname = usePathname();
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const token = getStoredToken();
    if (!token) {
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      return;
    }
    let cancelled = false;
    fetchSession(token)
      .then((s) => {
        if (cancelled) return;
        if (requireAdmin && s.role !== "admin") {
          router.replace("/incidents");
          return;
        }
        setSession(s);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        clearStoredToken();
        setError(err instanceof Error ? err.message : "session failed");
        router.replace("/login");
      });
    return () => {
      cancelled = true;
    };
  }, [pathname, requireAdmin, router]);

  function signOut() {
    clearStoredToken();
    router.replace("/login");
  }

  if (!session) {
    return (
      <div className="shell-loading">
        <p>{error ?? "Loading session…"}</p>
      </div>
    );
  }

  const isAdmin = session.role === "admin";

  return (
    <div className="shell">
      <header className="shell-header">
        <div className="shell-brand">
          <Link href="/incidents" className="brand-mark">
            IncidentPilot
          </Link>
          <span className="brand-sub">control plane</span>
        </div>
        <div className="shell-user">
          <span className="user-role">{session.role}</span>
          <span className="user-email">{session.email ?? session.actor_id}</span>
          <button type="button" className="btn-ghost" onClick={signOut}>
            Sign out
          </button>
        </div>
      </header>

      <div className="shell-body">
        <nav className="shell-nav" aria-label="Primary">
          <p className="nav-section">Ops</p>
          <ul>
            {OPS_LINKS.map((link) => (
              <li key={link.href}>
                <Link
                  href={link.href}
                  className={pathname.startsWith(link.href) ? "active" : undefined}
                >
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>

          {isAdmin ? (
            <>
              <p className="nav-section">Admin</p>
              <ul>
                {ADMIN_LINKS.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className={
                        pathname.startsWith(link.href) ? "active" : undefined
                      }
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </>
          ) : null}
        </nav>

        <main className="shell-main">
          <SessionProvider session={session}>{children}</SessionProvider>
        </main>
      </div>
    </div>
  );
}
