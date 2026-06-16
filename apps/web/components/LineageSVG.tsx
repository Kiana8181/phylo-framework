"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LineagePlot, LineagePlotNode, TreeNodeAttrs } from "@phylo/contracts";
import DownloadMenu from "@/components/phylo/tree/DownloadMenu";
import NodeDetailModal, { type NodeDetail } from "@/components/phylo/tree/NodeDetailModal";

type NodeAttrs = TreeNodeAttrs;

type RenderNode = {
  id: string;
  label: string;
  isLeaf: boolean;
  x: number;
  y: number;
  radius: number;
  color: string;
  title: string;
  displayLabel: string;
  rows: NodeDetail["rows"];
};

type RenderEdge = {
  key: string;
  d: string;
};

type LayoutWarning = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

type LayoutResult = {
  nodes: RenderNode[];
  edges: RenderEdge[];
  warnings: LayoutWarning[];
  svgWidth: number;
  svgHeight: number;
  labelX: number;
  connectorX: number;
  maxLabelChars: number;
};

const PAD = 24;
const MIN_CONTENT_WIDTH = 920;
const MIN_CONTENT_HEIGHT = 300;
const VIEWPORT_MAX_HEIGHT = 820;
const MIN_RADIUS = 3;
const MAX_RADIUS = 24;
const LABEL_FONT_SIZE = 11;
const LABEL_PAD = 10;
const LABEL_CONNECTOR_GAP = 4;
const MIN_LABEL_AREA = 40;
const MAX_LABEL_AREA = 120;
const LABEL_CHAR_WIDTH = 6.8;

const ABUNDANCE_PALETTE = [
  "#440154",
  "#482878",
  "#3E4A89",
  "#31688E",
  "#26828E",
  "#1F9E89",
  "#35B779",
  "#6CCE59",
  "#B4DD2C",
  "#FDE725",
] as const;

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

function toAbundance(value: unknown, fallback = 1): number {
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n <= 0) return fallback;
  return n;
}

function logNorm(value: number, min: number, max: number): number {
  const lo = Math.log1p(Math.max(0, min));
  const hi = Math.log1p(Math.max(0, max));
  const v = Math.log1p(Math.max(0, value));
  const span = hi - lo;
  if (span <= 0) return 0;
  return clamp((v - lo) / span, 0, 1);
}

function radiusForAbundance(value: number, min: number, max: number): number {
  const t = logNorm(value, min, max);
  return clamp(4 + t * 18, MIN_RADIUS, MAX_RADIUS);
}

function colorForAbundance(value: number, min: number, max: number): string {
  const t = logNorm(value, min, max);
  const idx = Math.round(t * (ABUNDANCE_PALETTE.length - 1));
  return ABUNDANCE_PALETTE[clamp(idx, 0, ABUNDANCE_PALETTE.length - 1)];
}

function resolveNodeAttrs(
  node: LineagePlotNode,
  nodeAttributes?: Record<string, NodeAttrs>,
): NodeAttrs | undefined {
  return nodeAttributes?.[node.label] ?? nodeAttributes?.[node.id];
}

function resolveDisplayLabel(
  node: LineagePlotNode,
  attrs: NodeAttrs | undefined,
  displayIdField?: string | null,
): string {
  if (displayIdField) {
    const selected = String(attrs?.[displayIdField] ?? "").trim();
    if (selected) return selected;
  }
  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq) return seq;
  const label = String(node.label ?? "").trim();
  if (label) return label;
  return node.id;
}

function buildTitle(
  node: LineagePlotNode,
  attrs: NodeAttrs | undefined,
  displayIdField?: string | null,
): string {
  if (typeof attrs?.tooltip === "string" && attrs.tooltip.trim()) {
    return attrs.tooltip.trim();
  }

  const lines: string[] = [];
  const display = resolveDisplayLabel(node, attrs, displayIdField);
  lines.push(display);

  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq && seq !== display) lines.push(`sequence_id: ${seq}`);

  const abundance = toAbundance(node.abundance ?? attrs?.abundance, 1);
  lines.push(`abundance: ${abundance}`);

  if (attrs && typeof attrs === "object") {
    const ignored = new Set<string>(["tooltip", "sequence_id", "abundance"]);
    if (displayIdField) ignored.add(displayIdField);

    const keys = Object.keys(attrs)
      .filter((key) => !ignored.has(key))
      .sort((a, b) => a.localeCompare(b, "en"));

    for (const key of keys) {
      const value = String(attrs[key] ?? "").trim();
      if (!value) continue;
      lines.push(`${key}: ${value}`);
    }
  }

  return lines.join("\n");
}

/** Structured field rows for the node-detail modal (clicking a node). */
function buildRows(node: LineagePlotNode, attrs: NodeAttrs | undefined): NodeDetail["rows"] {
  const rows: NodeDetail["rows"] = [{ key: "label", value: String(node.label ?? node.id) }];
  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq) rows.push({ key: "sequence_id", value: seq });
  rows.push({ key: "abundance", value: String(toAbundance(node.abundance ?? attrs?.abundance, 1)) });
  if (node.parentId) rows.push({ key: "parentId", value: String(node.parentId) });
  rows.push({ key: "type", value: node.isLeaf ? "leaf" : "internal" });
  if (attrs && typeof attrs === "object") {
    const ignored = new Set<string>(["tooltip", "sequence_id", "abundance"]);
    for (const key of Object.keys(attrs).filter((k) => !ignored.has(k)).sort((a, b) => a.localeCompare(b, "en"))) {
      const value = String(attrs[key] ?? "").trim();
      if (value) rows.push({ key, value });
    }
  }
  return rows;
}

function truncateLabel(label: string, maxChars: number): string {
  if (maxChars <= 1) return "…";
  if (label.length <= maxChars) return label;
  return `${label.slice(0, maxChars - 1).trimEnd()}…`;
}

function splitByHighlight(text: string, highlight: string): Array<{ text: string; highlight: boolean }> {
  if (!highlight || !highlight.trim()) return [{ text, highlight: false }];
  const parts: Array<{ text: string; highlight: boolean }> = [];
  const needle = highlight.trim();
  const lower = text.toLowerCase();
  const needleLower = needle.toLowerCase();
  let start = 0;
  while (true) {
    const i = lower.indexOf(needleLower, start);
    if (i === -1) {
      if (start < text.length) parts.push({ text: text.slice(start), highlight: false });
      break;
    }
    if (i > start) parts.push({ text: text.slice(start, i), highlight: false });
    parts.push({ text: text.slice(i, i + needle.length), highlight: true });
    start = i + needle.length;
  }
  return parts.length ? parts : [{ text, highlight: false }];
}

function resolveNodeDisplayLabel(
  node: LineagePlotNode,
  attrs: NodeAttrs | undefined,
  displayIdField: string | null | undefined,
  showInternalNodes: boolean,
  showNodeNumbers: boolean,
): string {
  if (!node.isLeaf && showInternalNodes) {
    const nodeId = String(attrs?.node_id ?? "").trim();
    const seq = String(attrs?.sequence ?? "").trim();
    const nodeNum = attrs?.nodeNumber ?? attrs?.node;
    if (showNodeNumbers && nodeNum != null && String(nodeNum).trim()) {
      const numLabel = `#${nodeNum}`;
      if (nodeId) return `${numLabel} ${nodeId}`;
      if (seq) return `${numLabel} ${seq.slice(0, 12)}`;
      return numLabel;
    }
    if (nodeId) return nodeId;
    if (seq) return seq.length > 16 ? `${seq.slice(0, 16)}…` : seq;
  }
  return resolveDisplayLabel(node, attrs, displayIdField);
}

function buildLayout(
  lineagePlot: LineagePlot,
  nodeAttributes: Record<string, NodeAttrs> | undefined,
  displayIdField: string | null | undefined,
  showLabels: boolean,
  showInternalNodes: boolean,
  showNodeNumbers: boolean,
): LayoutResult {
  const warnings: LayoutWarning[] = [];
  let invalidNodeCount = 0;
  let duplicateNodeCount = 0;
  let missingEdgeNodeCount = 0;
  const cleanNodes = (lineagePlot.nodes ?? []).filter((node) => {
    const valid = isFiniteNumber(node.x) && isFiniteNumber(node.y);
    if (!valid) invalidNodeCount += 1;
    return valid;
  });

  const byId = new Map<string, LineagePlotNode>();
  for (const node of cleanNodes) {
    if (byId.has(node.id)) {
      duplicateNodeCount += 1;
      continue;
    }
    byId.set(node.id, node);
  }

  const edges = (lineagePlot.edges ?? []).filter((edge) => {
    const valid = byId.has(edge.source) && byId.has(edge.target);
    if (!valid) missingEdgeNodeCount += 1;
    return valid;
  });

  if (invalidNodeCount > 0) {
    warnings.push({
      code: "invalid-node-coordinates",
      message: "Dropped lineage nodes with missing/invalid coordinates.",
      details: { droppedNodes: invalidNodeCount },
    });
  }
  if (duplicateNodeCount > 0) {
    warnings.push({
      code: "duplicate-node-id",
      message: "Duplicate lineage node IDs detected; only the first duplicate was rendered.",
      details: { droppedNodes: duplicateNodeCount },
    });
  }
  if (missingEdgeNodeCount > 0) {
    warnings.push({
      code: "missing-edge-node",
      message: "Dropped lineage edges that reference missing nodes.",
      details: { droppedEdges: missingEdgeNodeCount },
    });
  }

  if (byId.size === 0) {
    return {
      nodes: [],
      edges: [],
      warnings: [
        ...warnings,
        {
          code: "empty-lineage",
          message: "Lineage plot has no renderable nodes.",
        },
      ],
      svgWidth: MIN_CONTENT_WIDTH,
      svgHeight: MIN_CONTENT_HEIGHT,
      labelX: 0,
      connectorX: 0,
      maxLabelChars: 1,
    };
  }

  const coords = new Map<string, { x: number; y: number }>();
  for (const node of byId.values()) {
    coords.set(node.id, { x: node.x, y: node.y });
  }

  const xs = Array.from(coords.values()).map((point) => point.x);
  const ys = Array.from(coords.values()).map((point) => point.y);
  const rawWidth = Math.max(1, Math.max(...xs) - Math.min(...xs));
  const rawHeight = Math.max(1, Math.max(...ys) - Math.min(...ys));

  const readableScale = Math.max(1, 960 / rawWidth, 520 / rawHeight);
  if (readableScale > 1) {
    for (const [id, point] of coords) {
      coords.set(id, { x: point.x * readableScale, y: point.y * readableScale });
    }
  }

  const abundances = Array.from(byId.values()).map((node) => {
    const attrs = resolveNodeAttrs(node, nodeAttributes);
    return toAbundance(node.abundance ?? attrs?.abundance, 1);
  });
  const minAbundance = Math.min(...abundances);
  const maxAbundance = Math.max(...abundances);

  const preliminaryNodes = Array.from(byId.values()).map((node) => {
    const point = coords.get(node.id)!;
    const attrs = resolveNodeAttrs(node, nodeAttributes);
    const abundance = toAbundance(node.abundance ?? attrs?.abundance, 1);
    const radius = radiusForAbundance(abundance, minAbundance, maxAbundance);
    const displayLabel = resolveNodeDisplayLabel(
      node,
      attrs,
      displayIdField,
      showInternalNodes,
      showNodeNumbers,
    );
    return {
      id: node.id,
      label: node.label,
      isLeaf: node.isLeaf,
      x: point.x,
      y: point.y,
      radius,
      color: colorForAbundance(abundance, minAbundance, maxAbundance),
      title: buildTitle(node, attrs, displayIdField),
      displayLabel,
      rows: buildRows(node, attrs),
    };
  });

  let minX = Number.POSITIVE_INFINITY;
  let minY = Number.POSITIVE_INFINITY;
  let maxX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;

  for (const node of preliminaryNodes) {
    minX = Math.min(minX, node.x - node.radius);
    minY = Math.min(minY, node.y - node.radius);
    maxX = Math.max(maxX, node.x + node.radius);
    maxY = Math.max(maxY, node.y + node.radius);
  }

  const leafLabels = preliminaryNodes.filter((node) => node.isLeaf).map((node) => node.displayLabel);
  const maxChars = leafLabels.length ? Math.max(...leafLabels.map((label) => label.length)) : 0;
  const labelWidth = clamp(maxChars * LABEL_CHAR_WIDTH, MIN_LABEL_AREA, MAX_LABEL_AREA);
  const maxLabelChars = Math.max(1, Math.floor(labelWidth / LABEL_CHAR_WIDTH));
  const labelAreaWidth = showLabels || showInternalNodes ? LABEL_PAD + labelWidth : 0;
  if (showLabels || showInternalNodes) maxX += labelAreaWidth;

  const offsetX = PAD - minX;
  const offsetY = PAD - minY;

  const nodes = preliminaryNodes.map((node) => ({
    ...node,
    x: node.x + offsetX,
    y: node.y + offsetY,
  }));

  const plotRightX = nodes.reduce(
    (acc, node) => Math.max(acc, node.x + node.radius),
    Number.NEGATIVE_INFINITY,
  );
  const labelX = showLabels || showInternalNodes ? plotRightX + LABEL_PAD : 0;
  const connectorX = showLabels || showInternalNodes ? Math.round(labelX) - LABEL_CONNECTOR_GAP : 0;

  const renderEdges: RenderEdge[] = edges.map((edge, idx) => {
    const source = coords.get(edge.source);
    const target = coords.get(edge.target);
    if (!source || !target) {
      return { key: `${edge.source}-${edge.target}-${idx}`, d: "" };
    }

    const sx = source.x + offsetX;
    const sy = source.y + offsetY;
    const tx = target.x + offsetX;
    const ty = target.y + offsetY;

    return {
      key: `${edge.source}-${edge.target}-${idx}`,
      d: `M ${sx} ${sy} L ${sx} ${ty} L ${tx} ${ty}`,
    };
  });

  const contentWidth = Math.max(MIN_CONTENT_WIDTH, maxX - minX + PAD * 2);
  const contentHeight = Math.max(MIN_CONTENT_HEIGHT, maxY - minY + PAD * 2);

  return {
    nodes,
    edges: renderEdges.filter((edge) => edge.d),
    warnings,
    svgWidth: Math.ceil(contentWidth),
    svgHeight: Math.ceil(contentHeight),
    labelX: Math.round(labelX),
    connectorX,
    maxLabelChars,
  };
}

export default function LineageSVG({
  lineagePlot,
  nodeAttributes,
  displayIdField,
  showLabels = true,
  showInternalNodes = false,
  showNodeNumbers = false,
  filename = "tree",
  newickText,
  highlightText,
  viewportHeight,
}: {
  lineagePlot: LineagePlot;
  nodeAttributes?: Record<string, NodeAttrs>;
  displayIdField?: string | null;
  showLabels?: boolean;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
  filename?: string;
  newickText?: string | null;
  highlightText?: string | null;
  /** Override for the scrollable viewport height (e.g. fullscreen expand). */
  viewportHeight?: number | string;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);

  const layout = useMemo(
    () =>
      buildLayout(
        lineagePlot,
        nodeAttributes,
        displayIdField,
        showLabels,
        showInternalNodes ?? false,
        showNodeNumbers ?? false,
      ),
    [displayIdField, lineagePlot, nodeAttributes, showInternalNodes, showLabels, showNodeNumbers],
  );

  useEffect(() => {
    if (!layout.warnings.length) return;
    for (const warning of layout.warnings) {
      console.warn("[LineageSVG]", {
        code: warning.code,
        message: warning.message,
        details: warning.details,
      });
    }
  }, [layout.warnings]);

  function downloadSVG(): void {
    const svg = svgRef.current;
    if (!svg) return;

    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const blob = new Blob([src], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}-lineage.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function downloadPNG(): void {
    const svg = svgRef.current;
    if (!svg) return;

    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const img = new Image();

    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = layout.svgWidth;
      canvas.height = layout.svgHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      const png = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = png;
      a.download = `${filename}-lineage.png`;
      a.click();
    };

    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(src)}`;
  }

  function downloadNewick(): void {
    const txt = String(newickText ?? lineagePlot.meta?.normalizedNewick ?? "").trim();
    if (!txt) return;

    const normalized = txt.endsWith(";") ? txt : `${txt};`;
    const blob = new Blob([normalized], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.nwk`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (!layout.nodes.length) {
    return (
      <div className="space-y-2">
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          Unable to render lineage plot: no valid coordinates were provided.
        </div>
        {!!layout.warnings.length && (
          <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-800">
            {layout.warnings[0]?.message}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {!!layout.warnings.length && (
        <div className="rounded border border-amber-300 bg-amber-50 p-3 text-xs text-amber-900">
          {layout.warnings[0]?.message}
        </div>
      )}

      <div
        className="w-full overflow-auto rounded border"
        style={{ maxHeight: viewportHeight ?? VIEWPORT_MAX_HEIGHT }}
      >
        <svg
          ref={svgRef}
          width={layout.svgWidth}
          height={layout.svgHeight}
          data-tree-zoom-target="true"
          className="block bg-background text-foreground"
          role="img"
        >
          <g
            stroke="currentColor"
            strokeWidth={1.2}
            fill="none"
            opacity={0.8}
            vectorEffect="non-scaling-stroke"
          >
            {layout.edges.map((edge) => (
              <path key={edge.key} d={edge.d} />
            ))}
          </g>

          <g>
            {layout.nodes.map((node) => {
              const hovered = hoveredNodeId === node.id;
              const needle = highlightText?.trim();
              const matchesHighlight = Boolean(
                needle &&
                  (node.title.toLowerCase().includes(needle.toLowerCase()) ||
                    node.displayLabel.toLowerCase().includes(needle.toLowerCase()) ||
                    node.label.toLowerCase().includes(needle.toLowerCase()))
              );
              const circleFill = matchesHighlight ? "#dc2626" : node.color;
              const circleStroke = matchesHighlight
                ? "#b91c1c"
                : hovered
                  ? "#0f172a"
                  : "#111827";
              const circleStrokeWidth = matchesHighlight ? 2.5 : hovered ? 2.6 : 1.1;
              return (
                <g
                  key={node.id}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                  onClick={() => setSelectedNode({ title: node.displayLabel || node.label || node.id, rows: node.rows })}
                >
                  <circle
                    cx={node.x}
                    cy={node.y}
                    r={node.radius}
                    fill={circleFill}
                    stroke={circleStroke}
                    strokeWidth={circleStrokeWidth}
                    opacity={hovered || matchesHighlight ? 1 : 0.95}
                    style={{ cursor: "pointer" }}
                  >
                    <title>{node.title}</title>
                  </circle>
                  {((showLabels && node.isLeaf) || (showInternalNodes && !node.isLeaf)) && (
                    <g>
                      <line
                        x1={node.x}
                        y1={node.y}
                        x2={layout.connectorX}
                        y2={node.y}
                        stroke="currentColor"
                        strokeWidth={0.5}
                        opacity={0.4}
                        vectorEffect="non-scaling-stroke"
                      />
                      <text
                        x={layout.labelX}
                        y={node.y}
                        dominantBaseline="middle"
                        fontSize={LABEL_FONT_SIZE}
                        fill="currentColor"
                      >
                        {splitByHighlight(
                          truncateLabel(node.displayLabel, layout.maxLabelChars),
                          highlightText ?? ""
                        ).map((seg, i) =>
                          seg.highlight ? (
                            <tspan key={i} fill="#dc2626" fontWeight="bold">
                              {seg.text}
                            </tspan>
                          ) : (
                            <tspan key={i}>{seg.text}</tspan>
                          )
                        )}
                        <title>{node.title}</title>
                      </text>
                    </g>
                  )}
                </g>
              );
            })}
          </g>
        </svg>
      </div>

      <DownloadMenu
        formats={[
          { label: "PNG image", description: "Raster image of the current view", onSelect: downloadPNG },
          { label: "SVG image", description: "Scalable vector graphic", onSelect: downloadSVG },
          {
            label: "Newick",
            description: "Tree topology (.nwk)",
            onSelect: downloadNewick,
            disabled: !String(newickText ?? lineagePlot.meta?.normalizedNewick ?? "").trim(),
          },
        ]}
      />

      <NodeDetailModal detail={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
