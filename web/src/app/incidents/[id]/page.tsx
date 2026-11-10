"use client";

import Link from "next/link";
import { useParams } from "next/navigation";

import { AppShell } from "@/components/AppShell";

/** Placeholder until M3 detail skeleton. */
export default function IncidentStubPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id ?? "";

  return (
    <AppShell>
      <section className="panel">
        <h1>Incident</h1>
        <p>
          Detail view lands in M3.{" "}
          <span className="mono">{id}</span>
        </p>
        <p style={{ marginTop: "1rem" }}>
          <Link href="/incidents" className="mono-link">
            ← Back to list
          </Link>
        </p>
      </section>
    </AppShell>
  );
}
