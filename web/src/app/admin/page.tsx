"use client";

import { AppShell } from "@/components/AppShell";

export default function AdminPage() {
  return (
    <AppShell requireAdmin>
      <section className="panel">
        <h1>Admin</h1>
        <p>
          Admin-only area (policies, runbooks, integrations). Full surfaces land
          in M8 — navigation is gated on <code>role === admin</code>.
        </p>
      </section>
    </AppShell>
  );
}
