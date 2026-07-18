"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LineagePlot, TreeNodeAttrs } from "@phylo/contracts";
import { ZoomIn, ZoomOut, Maximize } from "lucide-react";
import { Button } from "@/components/ui/button";
import NodeDetailModal, { type NodeDetail } from "@/components/phylo/tree/NodeDetailModal";
import DownloadMenu from "@/components/phylo/tree/DownloadMenu";
import TreeSkeleton from "@/components/phylo/tree/TreeSkeleton";
import TreeLegend from "@/components/phylo/tree/TreeLegend";
import SvgTreeRenderer from "@/components/phylo/tree/renderers/SvgTreeRenderer";
import { useContainerSize } from "@/components/phylo/tree/hooks/useContainerSize";
import { useZoomPan } from "@/components/phylo/tree/hooks/useZoomPan";
import {
  fromLineagePlot,
  fromNewick,
  layoutTree,
  buildColorScale,
  buildTitle,
  buildRows,
  resolveNodeDisplayLabel,
  buildTipTitle,
  buildTipRows,
  resolveTipDisplayLabel,
  truncateLabel,
  serializeTreeSvg,
  downloadSvg,
  downloadPng,
  downloadNewick,
  defaultCollapsed,
  collapseAll,
  expandAll,
  toggleCollapse,
  subtreeColorSummary,
  FOCUS_SCALE,
  LOD_DETAIL_K,
  type NodeVisual,
  type EdgeVisual,
  type GlyphVisual,
  type PhyloAnnotation,
  type ColorScale,
} from "@/components/phylo/tree/core";

export type TreeSource =
  | { kind: "lineage"; lineagePlot: LineagePlot; nodeAttributes?: Record<string, TreeNodeAttrs> }
  | { kind: "phylogeny"; newick: string; annotations?: ReadonlyArray<PhyloAnnotation> };

export type CollapseSignal = { type: "expandAll" | "collapseAll"; nonce: number } | null;

export type TreeViewProps = {
  source: TreeSource;
  /** Display */
  displayIdField?: string | null;
  showLabels?: boolean;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
  /** Colour by (Phase 4). Concrete field: "abundance" | attr key | "none" | null.
   * Callers resolve the view-aware "auto" default before passing. */
  colorByField?: string | null;
  /** Cross-panel colour domain (union of values) so siblings agree. */
  colorDomain?: readonly string[] | null;
  /** Label whose value marks the germline/root (given its own token, excluded). */
  germlineLabel?: string | null;
  unknownValue?: string;
  onColorScaleChange?: (scale: ColorScale) => void;
  sizeBy?: string | null;
  /** Sequence Trace */
  highlightText?: string | null;
  markMatches?: boolean;
  focusSignal?: number;
  /** Collapse (Phase 3): bump `nonce` to expand-all / collapse-all. */
  collapseSignal?: CollapseSignal;
  /** Chrome */
  filename?: string;
  newickText?: string | null;
  height?: number | string;
  isLoading?: boolean;
  className?: string;
};

const DEFAULT_HEIGHT = 520;
const PHYLO_INTERNAL_RADIUS = 2.5;
const PHYLO_INTERNAL_HIT_RADIUS = 4; // invisible click target when internals hidden
const PHYLO_INTERNAL_FILL = "transparent";

export default function TreeView({
  source,
  displayIdField,
  showLabels = true,
  showInternalNodes = false,
  showNodeNumbers = false,
  colorByField = "abundance",
  colorDomain,
  germlineLabel,
  unknownValue,
  onColorScaleChange,
  sizeBy = null,
  highlightText,
  markMatches = false,
  focusSignal,
  collapseSignal,
  filename = "tree",
  newickText,
  height,
  isLoading = false,
  className,
}: TreeViewProps) {
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);
  const [highlightColor, setHighlightColor] = useState<string | null>(null);

  // Stable primitives for memo deps (caller passes a fresh `source` object each render).
  const lineagePlot = source.kind === "lineage" ? source.lineagePlot : null;
  const lineageAttrs = source.kind === "lineage" ? source.nodeAttributes : undefined;
  const newick = source.kind === "phylogeny" ? source.newick : "";
  const annotations = source.kind === "phylogeny" ? source.annotations : undefined;

  const model = useMemo(
    () =>
      source.kind === "lineage"
        ? fromLineagePlot(lineagePlot!, lineageAttrs)
        : fromNewick(newick, {
            annotations: annotations ? [...annotations] : undefined,
            sizeByField: sizeBy ?? null,
          }),
    [source.kind, lineagePlot, lineageAttrs, newick, annotations, sizeBy],
  );

  const isLineage = source.kind === "lineage";

  // Collapse state (a Set of ids) — never mutates the model. Reset per model.
  const [collapsed, setCollapsed] = useState<Set<string>>(() => defaultCollapsed(model));
  useEffect(() => {
    setCollapsed(defaultCollapsed(model));
  }, [model]);

  // Expand-all / Collapse-all broadcasts.
  const lastNonce = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!collapseSignal) return;
    if (lastNonce.current === collapseSignal.nonce) return;
    lastNonce.current = collapseSignal.nonce;
    setCollapsed(collapseSignal.type === "collapseAll" ? collapseAll(model) : expandAll());
  }, [collapseSignal, model]);

  const toggle = (id: string) => {
    const node = model.nodes.get(id);
    if (!node || node.childIds.length === 0) return; // leaves never collapse
    setCollapsed((prev) => toggleCollapse(prev, id));
  };

  const layout = useMemo(
    () =>
      layoutTree(model, {
        collapsed,
        showLabels,
        // Phylogeny internals never get right-column text labels (they get a
        // hollow ring + optional "#n"), so keep them out of the label geometry.
        showInternalNodes: isLineage ? showInternalNodes : false,
        displayLabelOf: isLineage
          ? (n) => resolveNodeDisplayLabel(n, displayIdField, showInternalNodes, showNodeNumbers)
          : (n) => resolveTipDisplayLabel(n.label, n.attrs, displayIdField ?? null),
      }),
    [model, collapsed, isLineage, showLabels, showInternalNodes, showNodeNumbers, displayIdField],
  );

  // Colour scale — one encoding for BOTH views (abundance / categorical / continuous).
  const colorScale = useMemo(
    () =>
      buildColorScale(model, colorByField ?? "none", {
        explicitValues: colorDomain ?? null,
        germlineLabel: germlineLabel ?? undefined,
        unknownValue,
      }),
    [model, colorByField, colorDomain, germlineLabel, unknownValue],
  );
  useEffect(() => {
    onColorScaleChange?.(colorScale);
  }, [colorScale, onColorScaleChange]);
  // Clear a legend highlight when the encoding changes.
  useEffect(() => {
    setHighlightColor(null);
  }, [colorScale]);

  const needle = highlightText?.trim().toLowerCase() ?? "";

  // Build the shared, layout-derived visuals once. SvgTreeRenderer AND the export
  // serialiser both consume these arrays (one source of truth for "what to draw").
  const { visuals, edges, glyphs, detailById, matchPoints } = useMemo(() => {
    const out: NodeVisual[] = [];
    const glyphOut: GlyphVisual[] = [];
    const details = new Map<string, NodeDetail>();
    const matches: Array<{ x: number; y: number }> = [];
    let internalCount = 0;

    for (const ln of layout.nodes) {
      const label = ln.node.label;
      const anno = ln.node.attrs;

      // Collapsed subtree → a wedge glyph (expand on click), no circle.
      if (ln.isCollapsed) {
        const summary = subtreeColorSummary(model, ln.id, (node) => {
          const c = colorScale.colorFor(node);
          return { key: c, color: c };
        });
        glyphOut.push({
          id: ln.id,
          apexX: ln.xPixel,
          y: ln.y,
          farX: ln.glyphFarXPixel ?? ln.xPixel,
          halfHeight: ln.glyphHalfHeight ?? 0,
          fill: summary ? summary.modalColor : colorScale.colorFor(ln.node),
          striped: summary ? summary.multiple : false,
          isMatch: false,
          labelText: showLabels
            ? `n=${ln.node.subtreeLeafCount} · Σ=${ln.node.subtreeAbundanceSum}`
            : null,
        });
        continue;
      }

      if (isLineage) {
        const fill = colorScale.colorFor(ln.node);
        const matched =
          !!needle &&
          (buildTitle(ln.node, displayIdField).toLowerCase().includes(needle) ||
            ln.displayLabel.toLowerCase().includes(needle) ||
            label.toLowerCase().includes(needle));
        out.push({
          id: ln.id,
          cx: ln.xPixel,
          cy: ln.y,
          r: ln.radius,
          fill,
          stroke: "#111827",
          strokeWidth: 1.1,
          hollow: false,
          isMatch: matched,
          ringed: highlightColor != null && fill === highlightColor,
          isCollapsible: ln.node.childIds.length > 0,
          labelShown: ln.labelShown,
          labelText: truncateLabel(ln.displayLabel, layout.maxLabelChars),
          numberText: null,
        });
        details.set(ln.id, { title: ln.displayLabel || label || ln.id, rows: buildRows(ln.node) });
        if (matched) matches.push({ x: ln.xPixel, y: ln.y });
        continue;
      }

      // Phylogeny
      if (ln.isLeaf) {
        const fill = colorScale.colorFor(ln.node);
        const displayLabel = resolveTipDisplayLabel(label, anno, displayIdField ?? null);
        const matched =
          !!needle &&
          (buildTipTitle(label, anno, colorScale.field, displayIdField ?? null)
            .toLowerCase()
            .includes(needle) ||
            label.toLowerCase().includes(needle) ||
            displayLabel.toLowerCase().includes(needle));
        out.push({
          id: ln.id,
          cx: ln.xPixel,
          cy: ln.y,
          r: ln.radius,
          fill,
          stroke: null,
          strokeWidth: 0,
          hollow: false,
          isMatch: matched,
          ringed: highlightColor != null && fill === highlightColor,
          isCollapsible: false,
          labelShown: showLabels,
          labelText: truncateLabel(displayLabel, layout.maxLabelChars),
          numberText: null,
        });
        details.set(ln.id, buildTipRows(label, anno, displayIdField ?? null));
        if (matched) matches.push({ x: ln.xPixel, y: ln.y });
      } else {
        // Internal node. When internals are shown: hollow ring + optional number.
        // When hidden: an invisible hit target so the branch point stays
        // collapsible (a chevron marks it at full zoom).
        internalCount += 1;
        out.push({
          id: ln.id,
          cx: ln.xPixel,
          cy: ln.y,
          r: showInternalNodes ? PHYLO_INTERNAL_RADIUS : PHYLO_INTERNAL_HIT_RADIUS,
          fill: showInternalNodes ? "none" : PHYLO_INTERNAL_FILL,
          stroke: showInternalNodes ? "currentColor" : null,
          strokeWidth: showInternalNodes ? 1.2 : 0,
          hollow: showInternalNodes,
          isMatch: false,
          ringed: false,
          isCollapsible: ln.node.childIds.length > 0,
          labelShown: false,
          labelText: "",
          numberText: showInternalNodes && showNodeNumbers ? `#${internalCount}` : null,
        });
        details.set(ln.id, buildTipRows(label, anno, displayIdField ?? null));
      }
    }

    const edgeVisuals: EdgeVisual[] = layout.edges.map((e) => ({
      key: e.key,
      d: `M ${e.sx} ${e.sy} L ${e.sx} ${e.ty} L ${e.tx} ${e.ty}`,
    }));

    return {
      visuals: out,
      edges: edgeVisuals,
      glyphs: glyphOut,
      detailById: details,
      matchPoints: matches,
    };
  }, [
    layout,
    model,
    isLineage,
    needle,
    displayIdField,
    showLabels,
    showInternalNodes,
    showNodeNumbers,
    colorScale,
    highlightColor,
  ]);

  // Zoom / pan. The svg is held as state (via a callback ref) so the zoom
  // behaviour attaches reliably even when the pane mounts after a skeleton.
  const { ref: containerRef, size } = useContainerSize<HTMLDivElement>();
  const [svgEl, setSvgEl] = useState<SVGSVGElement | null>(null);
  const zoomApi = useZoomPan({
    svgEl,
    contentWidth: layout.width,
    contentHeight: layout.height,
    containerWidth: size.width,
    containerHeight: size.height,
    // Re-fit only when the underlying tree changes (not on display/collapse toggles).
    fitKey: model,
  });

  // Two tiers: a compact "dots" overview only at extreme zoom-out, else "full".
  const k = zoomApi.transform.k || 1;
  const lod = k < LOD_DETAIL_K ? "dots" : "full";

  // "Show me" → centre/zoom on the matches (replaces scroll-to-match). Read latest
  // state via a ref so this fires only when focusSignal (the click) changes.
  const focusState = useRef({ matchPoints, markMatches, focusOn: zoomApi.focusOn });
  focusState.current = { matchPoints, markMatches, focusOn: zoomApi.focusOn };
  useEffect(() => {
    if (!focusSignal) return;
    const { matchPoints: mp, markMatches: mm, focusOn } = focusState.current;
    if (!mm || !mp.length) return;
    const xs = mp.map((p) => p.x);
    const ys = mp.map((p) => p.y);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
    focusOn(cx, cy, FOCUS_SCALE);
  }, [focusSignal]);

  const meta = {
    width: layout.width,
    height: layout.height,
    labelX: layout.labelX,
    connectorX: layout.connectorX,
    strokeWidth: 1,
  };
  const newickForExport =
    newickText ?? (isLineage ? lineagePlot?.meta?.normalizedNewick ?? "" : newick);

  if (isLoading) return <TreeSkeleton height={height} />;

  if (!visuals.length && !glyphs.length) {
    return (
      <div
        className="flex items-center justify-center rounded border bg-background p-6 text-sm text-muted-foreground"
        style={{ height: height ?? DEFAULT_HEIGHT }}
      >
        {layout.warnings[0]?.message ?? "No renderable tree data."}
      </div>
    );
  }

  return (
    <div
      ref={containerRef}
      className={`relative w-full overflow-hidden rounded border bg-background text-foreground ${className ?? ""}`}
      style={{ height: height ?? DEFAULT_HEIGHT }}
    >
      <svg ref={setSvgEl} className="absolute inset-0 h-full w-full touch-none select-none" role="img">
        <g transform={zoomApi.transform.toString()}>
          <SvgTreeRenderer
            nodes={visuals}
            edges={edges}
            glyphs={glyphs}
            transform={zoomApi.transform}
            lod={lod}
            labelX={layout.labelX}
            connectorX={layout.connectorX}
            highlightText={highlightText ?? null}
            markMatches={markMatches}
            onNodeClick={(id) => setSelectedNode(detailById.get(id) ?? null)}
            onToggleCollapse={toggle}
          />
        </g>
      </svg>

      {/* Legend (top-left) */}
      <TreeLegend
        scale={colorScale}
        activeColor={highlightColor}
        onToggle={(color) => setHighlightColor((prev) => (prev === color ? null : color))}
      />

      {/* Download (top-right) */}
      <div className="absolute right-3 top-3">
        <DownloadMenu
          formats={[
            {
              label: "PNG image",
              description: "Raster image of the whole tree",
              onSelect: () =>
                downloadPng(
                  serializeTreeSvg(visuals, edges, meta, glyphs),
                  meta.width,
                  meta.height,
                  `${filename}.png`,
                ),
            },
            {
              label: "SVG image",
              description: "Scalable vector graphic",
              onSelect: () => downloadSvg(serializeTreeSvg(visuals, edges, meta, glyphs), `${filename}.svg`),
            },
            {
              label: "Newick",
              description: "Tree topology (.nwk)",
              onSelect: () => downloadNewick(newickForExport, `${filename}.nwk`),
              disabled: !newickForExport.trim(),
            },
          ]}
        />
      </div>

      {/* Zoom controls (bottom-right) */}
      <div className="absolute bottom-3 right-3 flex flex-col gap-1.5">
        <Button type="button" variant="outline" size="icon" onClick={zoomApi.zoomIn} aria-label="Zoom in">
          <ZoomIn className="size-4" />
        </Button>
        <Button type="button" variant="outline" size="icon" onClick={zoomApi.zoomOut} aria-label="Zoom out">
          <ZoomOut className="size-4" />
        </Button>
        <Button
          type="button"
          variant="outline"
          size="icon"
          onClick={() => zoomApi.fitToView(undefined, true)}
          aria-label="Fit to view"
        >
          <Maximize className="size-4" />
        </Button>
      </div>

      <NodeDetailModal detail={selectedNode} onClose={() => setSelectedNode(null)} />
    </div>
  );
}
