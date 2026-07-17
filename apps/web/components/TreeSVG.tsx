"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import DownloadMenu from "@/components/phylo/tree/DownloadMenu";
import NodeDetailModal, { type NodeDetail } from "@/components/phylo/tree/NodeDetailModal";
import MatchArrow from "@/components/phylo/tree/MatchArrow";
import {
  fromNewick,
  layoutTree,
  sanitizeNewick,
  buildTipTitle,
  buildTipRows,
  resolveTipDisplayLabel,
  splitByHighlight,
  type PhyloAnnotation,
} from "@/components/phylo/tree/core";

type Anno = PhyloAnnotation;

type Props = {
  newick: string;
  width?: number;
  height?: number;
  filename?: string;
  fontSize?: number;
  strokeWidth?: number;
  showLabels?: boolean;
  annotations?: Anno[];
  colorMap?: Record<string, string>;
  colorBy?: string | null;
  unknownValue?: string;
  displayIdField?: string | null;
  /** When set, tip nodes whose label/tooltip contains this text get highlighted. */
  highlightText?: string | null;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
  /** Numeric annotation field used to scale tip circle radius. */
  sizeBy?: string | null;
  /** Override for the scrollable viewport height (e.g. fullscreen expand). */
  viewportHeight?: number | string;
  /** Draw a "Show me" arrow above every tip matching `highlightText`. */
  markMatches?: boolean;
  /** Bumping this scrolls the first matching tip into view (Sequence Trace). */
  focusSignal?: number;
};

const TREE_VIEWPORT_HEIGHT = 520;

/** ---- Colour-by-field helpers ----
 * These stay local for Phase 1; Phase 4 moves them into core/colorScale.ts and
 * adds continuous/categorical detection, an explicit domain, and a legend. */

const GOLDEN_ANGLE = 137.50776405003785;
const SAT_BANDS = [74, 62, 82, 55] as const;
const LIG_BANDS = [45, 58, 36, 66] as const;

function colorByIndex(k: number): string {
  const hue = (k * GOLDEN_ANGLE) % 360;
  const sat = SAT_BANDS[k % SAT_BANDS.length];
  const lig = LIG_BANDS[Math.floor(k / SAT_BANDS.length) % LIG_BANDS.length];
  return `hsl(${hue.toFixed(3)}, ${sat}%, ${lig}%)`;
}

function buildColorMapDistinct(
  list: Anno[] | undefined,
  field: string | null,
  unknownValue: string,
): Record<string, string> {
  const map: Record<string, string> = {};
  if (!list?.length || !field) return map;

  const set = new Set<string>();
  for (const a of list) {
    const v = a?.[field];
    if (typeof v === "string") {
      const vv = v.trim();
      if (vv && vv !== "Germline" && vv !== unknownValue) {
        set.add(vv);
      }
    }
  }
  const values = Array.from(set).sort((a, b) => a.localeCompare(b, "en"));

  values.forEach((v, i) => {
    map[v] = colorByIndex(i);
  });

  map["Germline"] = "#000000";
  map[unknownValue] = "#000000";
  return map;
}

function isBlackColor(value: string): boolean {
  const c = value.trim().toLowerCase();
  if (!c) return false;
  if (c === "black" || c === "#000" || c === "#000000" || c === "#000000ff") return true;

  const rgb = c.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const parts = rgb[1].split(",").map((v) => Number(v.trim()));
    if (parts.length >= 3) {
      const [r, g, b] = parts;
      return r === 0 && g === 0 && b === 0;
    }
  }

  return false;
}

export default function TreeSVG({
  newick,
  filename = "tree",
  fontSize = 12,
  strokeWidth = 1,
  showLabels = false,
  annotations,
  colorMap,
  colorBy,
  unknownValue,
  displayIdField,
  highlightText,
  showInternalNodes = false,
  showNodeNumbers = false,
  sizeBy = null,
  viewportHeight,
  markMatches = false,
  focusSignal,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);

  const coloringEnabled = !!colorBy;
  const colorField = colorBy || null;
  const unknown = (unknownValue && unknownValue.trim()) || "unknown";

  const colors = useMemo(() => {
    if (!coloringEnabled) return {} as Record<string, string>;
    if (colorMap && Object.keys(colorMap).length) {
      return { ...colorMap, Germline: "#000000", [unknown]: "#000000" };
    }
    return buildColorMapDistinct(annotations, colorField, unknown);
  }, [coloringEnabled, colorMap, annotations, colorField, unknown]);

  // Renderer-agnostic model + client-side layout (shared with the lineage view).
  const model = useMemo(
    () => fromNewick(newick, { annotations, sizeByField: sizeBy }),
    [newick, annotations, sizeBy],
  );

  const layout = useMemo(
    () =>
      layoutTree(model, {
        showLabels,
        showInternalNodes,
        displayLabelOf: (n) => resolveTipDisplayLabel(n.label, n.attrs, displayIdField),
      }),
    [model, showLabels, showInternalNodes, displayIdField],
  );

  const leaves = useMemo(() => layout.nodes.filter((n) => n.isLeaf), [layout.nodes]);
  const internals = useMemo(() => layout.nodes.filter((n) => !n.isLeaf), [layout.nodes]);

  // Tips matching the searched text (same predicate as the red highlight),
  // used to draw "Show me" arrows and to scroll the first match into view.
  const needle = highlightText?.trim() ?? "";
  const matchedTips = useMemo(() => {
    if (!needle) return [] as Array<{ x: number; y: number }>;
    const lc = needle.toLowerCase();
    const out: Array<{ x: number; y: number }> = [];
    for (const n of leaves) {
      const label = n.node.label;
      const anno = n.node.attrs;
      const title = buildTipTitle(label, anno, colorField, displayIdField || null);
      const displayLabel = resolveTipDisplayLabel(label, anno, displayIdField);
      if (
        title.toLowerCase().includes(lc) ||
        label.toLowerCase().includes(lc) ||
        displayLabel.toLowerCase().includes(lc)
      ) {
        out.push({ x: n.xPixel, y: n.y });
      }
    }
    return out;
  }, [needle, leaves, colorField, displayIdField]);

  // Read latest match state inside the focus effect without making it a dep,
  // so scrolling only fires when `focusSignal` (the "Show me" click) changes.
  const focusState = useRef({ matchedTips, markMatches });
  focusState.current = { matchedTips, markMatches };
  useEffect(() => {
    if (!focusSignal) return;
    const { matchedTips: tips, markMatches: mm } = focusState.current;
    const el = scrollRef.current;
    const first = tips[0];
    if (!mm || !el || !first) return;
    el.scrollTo({
      left: Math.max(0, first.x - el.clientWidth / 2),
      top: Math.max(0, first.y - el.clientHeight / 2),
      behavior: "smooth",
    });
  }, [focusSignal]);

  useEffect(() => {
    if (!layout.warnings.length) return;
    for (const warning of layout.warnings) {
      console.warn("[TreeSVG]", { code: warning.code, message: warning.message });
    }
  }, [layout.warnings]);

  function downloadSVG() {
    const svg = svgRef.current;
    if (!svg) return;
    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const blob = new Blob([src], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function downloadPNG() {
    const svg = svgRef.current;
    if (!svg) return;
    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = layout.width;
      canvas.height = layout.height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, layout.width, layout.height);
      ctx.drawImage(img, 0, 0);
      const png = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = png;
      a.download = `${filename}.png`;
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
  }

  function downloadNewick() {
    const txt = sanitizeNewick(newick);
    const blob = new Blob([txt], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.nwk`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="space-y-3">
      <div
        ref={scrollRef}
        className="w-full overflow-auto rounded border"
        style={{
          height: viewportHeight ?? TREE_VIEWPORT_HEIGHT,
          maxHeight: viewportHeight ?? TREE_VIEWPORT_HEIGHT,
        }}
      >
        <svg
          ref={svgRef}
          width={layout.width}
          height={layout.height}
          data-tree-zoom-target="true"
          className="block bg-background text-foreground"
          role="img"
        >
          {/* branches */}
          <g stroke="currentColor" strokeWidth={strokeWidth} fill="none" vectorEffect="non-scaling-stroke">
            {layout.edges.map((e) => (
              <path key={e.key} d={`M ${e.sx} ${e.sy} L ${e.sx} ${e.ty} L ${e.tx} ${e.ty}`} />
            ))}
          </g>

          {/* tips */}
          <g>
            {leaves.map((n) => {
              const label = n.node.label;
              const anno = n.node.attrs;
              const defaultLeafFill = "var(--foreground)";

              let fill = defaultLeafFill;
              if (coloringEnabled && colorField) {
                const call = (anno?.[colorField] as string) || "";
                if (call && call !== "Germline" && call !== unknown) {
                  const resolved = colors[call] ?? defaultLeafFill;
                  fill = isBlackColor(resolved) ? defaultLeafFill : resolved;
                }
              }

              const title = buildTipTitle(label, anno, colorField, displayIdField || null);
              const needleLc = highlightText?.trim();
              const displayLabel = resolveTipDisplayLabel(label, anno, displayIdField);
              const matchesHighlight = Boolean(
                needleLc &&
                  (title.toLowerCase().includes(needleLc.toLowerCase()) ||
                    label.toLowerCase().includes(needleLc.toLowerCase()) ||
                    displayLabel.toLowerCase().includes(needleLc.toLowerCase())),
              );
              const tipFill = matchesHighlight ? "#dc2626" : fill;
              const tipStroke = matchesHighlight ? "#b91c1c" : undefined;
              const tipStrokeWidth = matchesHighlight ? 2 : 0;

              return (
                <circle
                  key={n.id}
                  cx={n.xPixel}
                  cy={n.y}
                  r={n.radius}
                  fill={tipFill}
                  stroke={tipStroke}
                  strokeWidth={tipStrokeWidth}
                  style={{ cursor: "pointer" }}
                  onClick={() => setSelectedNode(buildTipRows(label, anno, displayIdField || null))}
                >
                  <title>{title}</title>
                </circle>
              );
            })}
          </g>

          {/* "Show me" arrows over matching tips */}
          {markMatches &&
            matchedTips.map((m, i) => <MatchArrow key={`tip-arrow-${i}`} x={m.x} y={m.y} />)}

          {showInternalNodes &&
            internals.map((n, i) => (
              <g key={`internal-${n.id}`}>
                <circle
                  cx={n.xPixel}
                  cy={n.y}
                  r={2.5}
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={1.2}
                  opacity={0.75}
                />
                {showNodeNumbers && (
                  <text x={n.xPixel + 6} y={n.y - 6} fontSize={9} fill="currentColor" opacity={0.8}>
                    {`#${i + 1}`}
                  </text>
                )}
              </g>
            ))}

          {/* labels */}
          {showLabels && (
            <g fontSize={fontSize} fill="currentColor">
              {leaves.map((n) => {
                const label = n.node.label;
                const anno = n.node.attrs;
                const title = buildTipTitle(label, anno, colorField, displayIdField || null);
                const displayLabel = n.displayLabel;
                const labelParts = splitByHighlight(displayLabel, highlightText ?? "");
                const needleLc = highlightText?.trim();
                const labelMatches = Boolean(
                  needleLc &&
                    (title.toLowerCase().includes(needleLc.toLowerCase()) ||
                      label.toLowerCase().includes(needleLc.toLowerCase()) ||
                      displayLabel.toLowerCase().includes(needleLc.toLowerCase())),
                );
                return (
                  <g key={`label-${n.id}`}>
                    <line
                      x1={n.xPixel}
                      y1={n.y}
                      x2={layout.connectorX}
                      y2={n.y}
                      stroke="currentColor"
                      strokeWidth={0.5}
                      opacity={0.4}
                      vectorEffect="non-scaling-stroke"
                    />
                    <text
                      x={layout.labelX}
                      y={n.y}
                      dominantBaseline="middle"
                      fill={labelMatches ? "#dc2626" : undefined}
                      fontWeight={labelMatches ? "bold" : undefined}
                    >
                      {labelParts.map((seg, j) =>
                        seg.highlight ? (
                          <tspan key={j} fill="#dc2626" fontWeight="bold">
                            {seg.text}
                          </tspan>
                        ) : (
                          <tspan key={j}>{seg.text}</tspan>
                        ),
                      )}
                      <title>{title}</title>
                    </text>
                  </g>
                );
              })}
            </g>
          )}
        </svg>
      </div>

      <DownloadMenu
        className="mt-3"
        formats={[
          { label: "PNG image", description: "Raster image of the current view", onSelect: downloadPNG },
          { label: "SVG image", description: "Scalable vector graphic", onSelect: downloadSVG },
          { label: "Newick", description: "Tree topology (.nwk)", onSelect: downloadNewick },
        ]}
      />

      <NodeDetailModal detail={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
