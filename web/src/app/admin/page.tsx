"use client";

import { useState } from "react";

import { AdminIntegrationsPanel } from "@/components/AdminIntegrationsPanel";
import { AdminPoliciesPanel } from "@/components/AdminPoliciesPanel";
import { AdminRunbooksPanel } from "@/components/AdminRunbooksPanel";
import { AppShell } from "@/components/AppShell";

const TABS = [
  { id: "policies", label: "Policies" },
  { id: "runbooks", label: "Runbooks" },
  { id: "integrations", label: "Integrations" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function AdminPage() {
  const [tab, setTab] = useState<TabId>("policies");

  return (
    <AppShell requireAdmin>
      <section className="page-head">
        <div>
          <h1>Admin</h1>
          <p className="lede">
            Policies, runbook publish, and integration scope — admin only.
            Secrets are never displayed.
          </p>
        </div>
      </section>

      <nav className="admin-tabs" aria-label="Admin sections">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={tab === t.id ? "admin-tab active" : "admin-tab"}
            onClick={() => setTab(t.id)}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === "policies" ? <AdminPoliciesPanel /> : null}
      {tab === "runbooks" ? <AdminRunbooksPanel /> : null}
      {tab === "integrations" ? <AdminIntegrationsPanel /> : null}
    </AppShell>
  );
}
