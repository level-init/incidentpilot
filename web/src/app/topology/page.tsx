"use client";

import { AppShell } from "@/components/AppShell";
import { ServiceDependencyMap } from "@/components/ServiceDependencyMap";

export default function TopologyPage() {
  return (
    <AppShell>
      <header className="page-head">
        <h1>Topology</h1>
        <p className="lede">
          Sim world call graph from{" "}
          <span className="mono">domain.service_dependency</span> (Postgres —
          not Neo4j). Open an incident to see blast-radius highlighting.
        </p>
      </header>
      <ServiceDependencyMap environment="local" />
    </AppShell>
  );
}
