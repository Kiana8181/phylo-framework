"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LineagePlot, TreeNodeAttrs } from "@phylo/contracts";
import DownloadMenu from "@/components/phylo/tree/DownloadMenu";
import NodeDetailModal, { type NodeDetail } from "@/components/phylo/tree/NodeDetailModal";
import MatchArrow from "@/components/phylo/tree/MatchArrow";
import {
  fromLineagePlot,
  layoutTree,
  colorForAbundance,
  buildTitle,
  buildRows,
  resolveNodeDisplayLabel,
  truncateLabel,
  splitByHighlight,
  LABEL_FONT_SIZE,
} from "@/components/phylo/tree/core";

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

// Scroll-container height fallback (Phase 2 replaces the scroll container with a
// measured zoom/pan pane).
const VIEWPORT_MAX_HEIGHT = 820;

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
  markMatches = false,
  focusSignal,
  fitToParent = false,
  onRequestFocus,
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
  /** Draw a "Show me" arrow above every node matching `highlightText`. */
  markMatches?: boolean;
  /** Bumping this focuses the first matching node (Sequence Trace). */
  focusSignal?: number;
  /** Render the bare svg only (no own scroll), to be driven by a zoom pane. */
  fitToParent?: boolean;
  /** In `fitToParent` mode, report the first match's coords instead of scrolling. */
  onRequestFocus?: (x: number, y: number) => void;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null);
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);

  const model = useMemo(
    () => fromLineagePlot(lineagePlot, nodeAttributes),
    [lineagePlot, nodeAttributes],
  );

  const layout = useMemo(() => {
    const tl = layoutTree(model, {
      showLabels,
      showInternalNodes: showInternalNodes ?? false,
      displayLabelOf: (n) =>
        resolveNodeDisplayLabel(n, displayIdField, showInternalNodes ?? false, showNodeNumbers ?? false),
    });
    const nodes: RenderNode[] = tl.nodes.map((ln) => ({
      id: ln.id,
      label: ln.node.label,
      isLeaf: ln.isLeaf,
      x: ln.xPixel,
      y: ln.y,
      radius: ln.radius,
      color: colorForAbundance(ln.node.abundance, tl.abundanceMin, tl.abundanceMax),
      title: buildTitle(ln.node, displayIdField),
      displayLabel: ln.displayLabel,
      rows: buildRows(ln.node),
    }));
    const edges = tl.edges.map((e) => ({
      key: e.key,
      d: `M ${e.sx} ${e.sy} L ${e.sx} ${e.ty} L ${e.tx} ${e.ty}`,
    }));
    return {
      nodes,
      edges,
      warnings: tl.warnings,
      svgWidth: tl.width,
      svgHeight: tl.height,
      labelX: tl.labelX,
      connectorX: tl.connectorX,
      maxLabelChars: tl.maxLabelChars,
    };
  }, [model, displayIdField, showLabels, showInternalNodes, showNodeNumbers]);

  // Nodes matching the searched text (same predicate as the red highlight),
  // used to scroll the first match into view on "Show me".
  const needle = highlightText?.trim() ?? "";
  const matchedNodes = useMemo(() => {
    if (!needle) return [] as Array<{ x: number; y: number }>;
    const lc = needle.toLowerCase();
    return layout.nodes
      .filter(
        (node) =>
          node.title.toLowerCase().includes(lc) ||
          node.displayLabel.toLowerCase().includes(lc) ||
          node.label.toLowerCase().includes(lc),
      )
      .map((node) => ({ x: node.x, y: node.y }));
  }, [needle, layout.nodes]);

  const focusState = useRef({ matchedNodes, markMatches, fitToParent, onRequestFocus });
  focusState.current = { matchedNodes, markMatches, fitToParent, onRequestFocus };
  useEffect(() => {
    if (!focusSignal) return;
    const { matchedNodes: nodes, markMatches: mm, fitToParent: fit, onRequestFocus: req } =
      focusState.current;
    const first = nodes[0];
    if (!mm || !first) return;
    // In a zoom pane, hand the coordinate to the parent to zoom-and-center;
    // otherwise scroll our own container so the first match is centered.
    if (fit) {
      req?.(first.x, first.y);
      return;
    }
    const el = scrollRef.current;
    if (!el) return;
    el.scrollTo({
      left: Math.max(0, first.x - el.clientWidth / 2),
      top: Math.max(0, first.y - el.clientHeight / 2),
      behavior: "smooth",
    });
  }, [focusSignal]);

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

  const svgEl = (
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
                  {markMatches && matchesHighlight && (
                    <MatchArrow x={node.x} y={node.y} gap={node.radius + 6} />
                  )}
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
                        fill={matchesHighlight ? "#dc2626" : "currentColor"}
                        fontWeight={matchesHighlight ? "bold" : undefined}
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
  );

  const modal = <NodeDetailModal detail={selectedNode} onClose={() => setSelectedNode(null)} />;

  // Zoom-pane mode: render the bare svg so TreeZoomPane controls fit/zoom/pan.
  if (fitToParent) {
    return (
      <>
        {svgEl}
        {modal}
      </>
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
        ref={scrollRef}
        className="w-full overflow-auto rounded border"
        style={{ maxHeight: viewportHeight ?? VIEWPORT_MAX_HEIGHT }}
      >
        {svgEl}
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

      {modal}
    </div>
  );
}
