"use client";

import { useEffect, useMemo, useState } from "react";

import {
  getIncidentDependencyMap,
  getTopologyDependencies,
  type DependencyMap,
  type DependencyNode,
} from "@/lib/api";

type Props = {
  /** When set, loads incident overlay (linked + propagation). */
  incidentId?: string;
  environment?: string;
  compact?: boolean;
};

type LayoutNode = DependencyNode & { x: number; y: number };

function layoutNodes(nodes: DependencyNode[]): LayoutNode[] {
  if (nodes.length === 0) return [];
  const callers = new Set(
    nodes
      .filter((n) =>
        // Approximate tiers: gateway-like callers first if named gateway
        n.key === "gateway",
      )
      .map((n) => n.key),
  );
  const linked = nodes.filter((n) => n.linked);
  const downstream = nodes.filter((n) => n.downstream && !n.linked);
  const upstream = nodes.filter((n) => n.upstream && !n.linked);
  const rest = nodes.filter(
    (n) => !n.linked && !n.upstream && !n.downstream,
  );

  // Prefer gateway row as top when present; otherwise callers of linked.
  const top =
    downstream.length > 0
      ? downstream
      : nodes.filter((n) => callers.has(n.key) && !n.linked);
  const mid = linked.length > 0 ? linked : nodes.slice(0, Math.ceil(nodes.length / 2));
  const bottom =
    upstream.length > 0
      ? upstream
      : rest.filter((n) => !mid.some((m) => m.key === n.key));
  const leftovers = nodes.filter(
    (n) =>
      !top.some((t) => t.key === n.key) &&
      !mid.some((m) => m.key === n.key) &&
      !bottom.some((b) => b.key === n.key),
  );

  const rows: DependencyNode[][] = [
    top.length ? top : [],
    mid.length ? mid : [],
    [...bottom, ...leftovers],
  ].filter((r) => r.length > 0);

  const width = 640;
  const height = 220;
  const padX = 48;
  const padY = 36;
  const out: LayoutNode[] = [];
  rows.forEach((row, ri) => {
    const y =
      rows.length === 1
        ? height / 2
        : padY + (ri * (height - 2 * padY)) / Math.max(1, rows.length - 1);
    row.forEach((n, ci) => {
      const x =
        row.length === 1
          ? width / 2
          : padX + (ci * (width - 2 * padX)) / Math.max(1, row.length - 1);
      out.push({ ...n, x, y });
    });
  });
  return out;
}

function nodeClass(n: DependencyNode): string {
  if (n.linked) return "dep-node dep-node-linked";
  if (n.downstream) return "dep-node dep-node-down";
  if (n.upstream) return "dep-node dep-node-up";
  return "dep-node";
}

export function ServiceDependencyMap({
  incidentId,
  environment = "local",
  compact = false,
}: Props) {
  const [map, setMap] = useState<DependencyMap | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const load = incidentId
      ? getIncidentDependencyMap(incidentId, environment)
      : getTopologyDependencies(environment);
    load
      .then((data) => {
        if (!cancelled) {
          setMap(data);
          setError(null);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setMap(null);
          setError(err instanceof Error ? err.message : "map load failed");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [incidentId, environment]);

  const layout = useMemo(
    () => (map ? layoutNodes(map.nodes) : []),
    [map],
  );
  const byKey = useMemo(() => {
    const m = new Map<string, LayoutNode>();
    for (const n of layout) m.set(n.key, n);
    return m;
  }, [layout]);

  return (
    <section
      className={`dep-map ${compact ? "dep-map-compact" : ""}`}
      aria-label="Service dependency map"
    >
      <header className="pane-head">
        <div>
          <p className="pane-kicker">Blast radius · ServiceDependency</p>
          <h2>Dependency map</h2>
        </div>
        <span className="pane-count">
          {map ? `${map.nodes.length} svc · ${map.edges.length} edges` : "…"}
        </span>
      </header>

      {error ? <p className="login-error">{error}</p> : null}

      {map === null && !error ? <p>Loading topology…</p> : null}

      {map && map.nodes.length === 0 ? (
        <p className="lede">No services in catalog for {environment}.</p>
      ) : null}

      {map && map.nodes.length > 0 ? (
        <>
          <div className="dep-legend" aria-label="Legend">
            <span className="dep-leg dep-leg-linked">Linked</span>
            <span className="dep-leg dep-leg-down">Downstream (callers)</span>
            <span className="dep-leg dep-leg-up">Upstream (callees)</span>
            <span className="dep-leg">Catalog</span>
          </div>

          {(map.linked_service_keys.length > 0 ||
            map.upstream_keys.length > 0 ||
            map.downstream_keys.length > 0) && (
            <dl className="dep-prop">
              <div>
                <dt>Linked</dt>
                <dd className="mono">
                  {map.linked_service_keys.length
                    ? map.linked_service_keys.join(", ")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Propagates to</dt>
                <dd className="mono">
                  {map.downstream_keys.length
                    ? map.downstream_keys.join(", ")
                    : "—"}
                </dd>
              </div>
              <div>
                <dt>Depends on</dt>
                <dd className="mono">
                  {map.upstream_keys.length
                    ? map.upstream_keys.join(", ")
                    : "—"}
                </dd>
              </div>
            </dl>
          )}

          <svg
            className="dep-svg"
            viewBox="0 0 640 220"
            role="img"
            aria-label="Service call graph"
          >
            {map.edges.map((e) => {
              const a = byKey.get(e.from_key);
              const b = byKey.get(e.to_key);
              if (!a || !b) return null;
              return (
                <line
                  key={e.edge_id}
                  x1={a.x}
                  y1={a.y}
                  x2={b.x}
                  y2={b.y}
                  className={
                    e.on_propagation_path
                      ? "dep-edge dep-edge-hot"
                      : "dep-edge"
                  }
                />
              );
            })}
            {layout.map((n) => (
              <g key={n.service_id} transform={`translate(${n.x},${n.y})`}>
                <circle r={18} className={nodeClass(n)} />
                <text y={4} textAnchor="middle" className="dep-label">
                  {n.key.length > 10 ? `${n.key.slice(0, 9)}…` : n.key}
                </text>
              </g>
            ))}
          </svg>

          <ul className="dep-list" aria-label="Services">
            {map.nodes.map((n) => (
              <li key={n.service_id}>
                <span className={`dep-dot ${nodeClass(n)}`} />
                <span className="mono">{n.key}</span>
                <span className="chip">{n.criticality}</span>
                {n.linked ? <span className="chip">linked</span> : null}
                {n.downstream ? <span className="chip">downstream</span> : null}
                {n.upstream ? <span className="chip">upstream</span> : null}
              </li>
            ))}
          </ul>
        </>
      ) : null}
    </section>
  );
}
