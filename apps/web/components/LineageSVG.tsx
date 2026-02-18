"use client";

import { useMemo } from "react";

type NodeAttrs = Record<string, any>;

type LineageNode = {
  id: string;
  label: string;
  x: number;
  y: number;
  isLeaf: boolean;
  parentId?: string;
  abundance?: number;
};

type LineageEdge = {
  source: string;
  target: string;
};

type LineagePlot = {
  format: "lineage-plot-v1";
  nodes: LineageNode[];
  edges: LineageEdge[];
  meta?: {
    rootId?: string;
    germlineLabel?: string;
    width?: number;
    height?: number;
  };
};

function toNumber(v: unknown, fallback = 1): number {
  const n = typeof v === "number" ? v : Number(v);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return n;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function nodeRadius(node: LineageNode, attrs?: NodeAttrs): number {
  const a = toNumber(node.abundance ?? attrs?.abundance, 1);
  return clamp(3 + Math.sqrt(a), 3, 16);
}

function buildTitle(node: LineageNode, attrs?: NodeAttrs, displayIdField?: string | null): string {
  if (typeof attrs?.tooltip === "string" && attrs.tooltip.trim()) {
    return attrs.tooltip.trim();
  }
  const lines: string[] = [];
  const display =
    (displayIdField && String(attrs?.[displayIdField] ?? "").trim()) || node.label || node.id;
  lines.push(display);

  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq && seq !== display) lines.push(`sequence_id: ${seq}`);

  const abundance = toNumber(node.abundance ?? attrs?.abundance, 1);
  lines.push(`abundance: ${abundance}`);

  if (attrs && typeof attrs === "object") {
    const extraKeys = Object.keys(attrs)
      .filter((k) => !["tooltip", "sequence_id", "abundance", displayIdField ?? ""].includes(k))
      .sort((a, b) => a.localeCompare(b, "en"));
    for (const k of extraKeys) {
      const v = String(attrs[k] ?? "").trim();
      if (!v) continue;
      lines.push(`${k}: ${v}`);
    }
  }

  return lines.join("\n");
}

export default function LineageSVG({
  lineagePlot,
  nodeAttributes,
  displayIdField,
}: {
  lineagePlot: LineagePlot;
  nodeAttributes?: Record<string, NodeAttrs>;
  displayIdField?: string | null;
}) {
  const byId = useMemo(() => {
    const m: Record<string, LineageNode> = {};
    for (const n of lineagePlot.nodes ?? []) m[n.id] = n;
    return m;
  }, [lineagePlot.nodes]);

  const view = useMemo(() => {
    const nodes = lineagePlot.nodes ?? [];
    if (!nodes.length) return { minX: 0, minY: 0, width: 900, height: 520 };

    const xs = nodes.map((n) => n.x);
    const ys = nodes.map((n) => n.y);
    const minX = Math.min(...xs) - 30;
    const maxX = Math.max(...xs) + 30;
    const minY = Math.min(...ys) - 30;
    const maxY = Math.max(...ys) + 30;
    const width = Math.max(600, maxX - minX);
    const height = Math.max(320, maxY - minY);
    return { minX, minY, width, height };
  }, [lineagePlot.nodes]);

  return (
    <div className="w-full overflow-auto">
      <svg
        width="100%"
        height={Math.round(Math.max(320, lineagePlot.meta?.height ?? view.height))}
        viewBox={`${view.minX} ${view.minY} ${view.width} ${view.height}`}
        className="rounded border bg-background text-foreground"
        role="img"
      >
        <g stroke="currentColor" strokeWidth={1.2} opacity={0.65}>
          {(lineagePlot.edges ?? []).map((e, i) => {
            const a = byId[e.source];
            const b = byId[e.target];
            if (!a || !b) return null;
            return <line key={`${e.source}-${e.target}-${i}`} x1={a.x} y1={a.y} x2={b.x} y2={b.y} />;
          })}
        </g>

        <g>
          {(lineagePlot.nodes ?? []).map((n) => {
            const attrs = nodeAttributes?.[n.label] ?? nodeAttributes?.[n.id];
            const r = nodeRadius(n, attrs);
            const title = buildTitle(n, attrs, displayIdField || null);
            const fill = n.isLeaf ? "#0f766e" : "#334155";
            const display =
              (displayIdField && String(attrs?.[displayIdField] ?? "").trim()) || n.label || n.id;
            return (
              <g key={n.id}>
                <circle cx={n.x} cy={n.y} r={r} fill={fill}>
                  <title>{title}</title>
                </circle>
                <text x={n.x + r + 5} y={n.y} dominantBaseline="middle" fontSize={11}>
                  {display}
                  <title>{title}</title>
                </text>
              </g>
            );
          })}
        </g>
      </svg>
    </div>
  );
}
