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
  /** Require eval entitlement (orthogonal to ops role). */
  requireEval?: boolean;
};

const OPS_LINKS = [
  { href: "/incidents", label: "Incidents" },
  { href: "/topology", label: "Topology" },
] as const;

const ADMIN_LINKS = [
  { href: "/admin", label: "Admin" },
] as const;

const EVAL_LINKS = [
  { href: "/eval", label: "Scenario runs" },
  { href: "/eval/ground-truth", label: "Ground truth" },
] as const;

export function AppShell({
  children,
  requireAdmin = false,
  requireEval = false,
}: Props) {
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
        if (requireEval && !s.eval_entitled) {
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
  }, [pathname, requireAdmin, requireEval, router]);

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
  const isEval = session.eval_entitled;
  const onEvalSurface = pathname.startsWith("/eval");

  return (
    <div className={onEvalSurface ? "shell shell-eval" : "shell"}>
      <header className="shell-header">
        <div className="shell-brand">
          <Link href="/incidents" className="brand-mark">
            IncidentPilot
          </Link>
          <span className="brand-sub">
            {onEvalSurface ? "evaluation" : "control plane"}
          </span>
        </div>
        <div className="shell-user">
          <span className="user-role">{session.role}</span>
          {isEval ? <span className="user-eval">eval</span> : null}
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

          {isEval ? (
            <>
              <p className="nav-section">Eval</p>
              <ul>
                {EVAL_LINKS.map((link) => {
                  const active =
                    link.href === "/eval"
                      ? pathname === "/eval" ||
                        pathname.startsWith("/eval/runs")
                      : pathname.startsWith(link.href);
                  return (
                    <li key={link.href}>
                      <Link
                        href={link.href}
                        className={active ? "active" : undefined}
                      >
                        {link.label}
                      </Link>
                    </li>
                  );
                })}
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
