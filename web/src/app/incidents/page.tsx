"use client";

import { AppShell } from "@/components/AppShell";

export default function IncidentsPage() {
  return (
    <AppShell>
      <section className="panel">
        <h1>Incidents</h1>
        <p>
          Ops workspace. Incident list and detail land in M2/M3 — this shell
          confirms session login and the ops navigation.
        </p>
      </section>
    </AppShell>
  );
}
