"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import type { LineagePlot, TreeNodeAttrs } from "@phylo/contracts";
import { ZoomIn, ZoomOut, Maximize } from "lucide-react";
import { Button } from "@/components/ui/button";
import NodeDetailModal, { type NodeDetail } from "@/components/phylo/tree/NodeDetailModal";
import DownloadMenu from "@/components/phylo/tree/DownloadMenu";
import TreeSkeleton from "@/components/phylo/tree/TreeSkeleton";
import SvgTreeRenderer from "@/components/phylo/tree/renderers/SvgTreeRenderer";
import { buildColorMapDistinct, isBlackColor } from "@/components/phylo/tree/renderers/phyloColor";
import { useContainerSize } from "@/components/phylo/tree/hooks/useContainerSize";
import { useZoomPan } from "@/components/phylo/tree/hooks/useZoomPan";
import {
  fromLineagePlot,
  fromNewick,
  layoutTree,
  colorForAbundance,
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
  FOCUS_SCALE,
  type NodeVisual,
  type EdgeVisual,
  type PhyloAnnotation,
} from "@/components/phylo/tree/core";

export type TreeSource =
  | { kind: "lineage"; lineagePlot: LineagePlot; nodeAttributes?: Record<string, TreeNodeAttrs> }
  | { kind: "phylogeny"; newick: string; annotations?: ReadonlyArray<PhyloAnnotation> };

export type TreeViewProps = {
  source: TreeSource;
  /** Display */
  displayIdField?: string | null;
  showLabels?: boolean;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
  /** Phylogeny colour passthrough (Phase 4 replaces with colorByField + legend). */
  colorBy?: string | null;
  unknownValue?: string;
  colorMap?: Record<string, string>;
  sizeBy?: string | null;
  /** Sequence Trace */
  highlightText?: string | null;
  markMatches?: boolean;
  focusSignal?: number;
  /** Chrome */
  filename?: string;
  newickText?: string | null;
  height?: number | string;
  isLoading?: boolean;
  className?: string;
};

const DEFAULT_HEIGHT = 520;
const PHYLO_INTERNAL_RADIUS = 2.5;

export default function TreeView({
  source,
  displayIdField,
  showLabels = true,
  showInternalNodes = false,
  showNodeNumbers = false,
  colorBy,
  unknownValue,
  colorMap,
  sizeBy = null,
  highlightText,
  markMatches = false,
  focusSignal,
  filename = "tree",
  newickText,
  height,
  isLoading = false,
  className,
}: TreeViewProps) {
  const [selectedNode, setSelectedNode] = useState<NodeDetail | null>(null);

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

  const layout = useMemo(
    () =>
      layoutTree(model, {
        showLabels,
        // Phylogeny internals never get right-column text labels (they get a
        // hollow ring + optional "#n"), so keep them out of the label geometry.
        showInternalNodes: isLineage ? showInternalNodes : false,
        displayLabelOf: isLineage
          ? (n) => resolveNodeDisplayLabel(n, displayIdField, showInternalNodes, showNodeNumbers)
          : (n) => resolveTipDisplayLabel(n.label, n.attrs, displayIdField ?? null),
      }),
    [model, isLineage, showLabels, showInternalNodes, showNodeNumbers, displayIdField],
  );

  // Phylogeny colour map (unchanged behaviour; Phase 4 unifies into core).
  const coloringEnabled = !isLineage && !!colorBy;
  const colorField = colorBy || null;
  const unknown = (unknownValue && unknownValue.trim()) || "unknown";
  const phyloColors = useMemo(() => {
    if (!coloringEnabled) return {} as Record<string, string>;
    if (colorMap && Object.keys(colorMap).length) {
      return { ...colorMap, Germline: "#000000", [unknown]: "#000000" };
    }
    return buildColorMapDistinct(
      annotations ? [...annotations] : undefined,
      colorField,
      unknown,
    );
  }, [coloringEnabled, colorMap, annotations, colorField, unknown]);

  const needle = highlightText?.trim().toLowerCase() ?? "";

  // Build the shared, layout-derived visuals once. SvgTreeRenderer AND the export
  // serialiser both consume this array (one source of truth for "what to draw").
  const { visuals, edges, detailById, matchPoints } = useMemo(() => {
    const out: NodeVisual[] = [];
    const details = new Map<string, NodeDetail>();
    const matches: Array<{ x: number; y: number }> = [];
    let internalCount = 0;

    for (const ln of layout.nodes) {
      const label = ln.node.label;
      const anno = ln.node.attrs;

      if (isLineage) {
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
          fill: colorForAbundance(ln.node.abundance, layout.abundanceMin, layout.abundanceMax),
          stroke: "#111827",
          strokeWidth: 1.1,
          hollow: false,
          isMatch: matched,
          labelShown: ln.labelShown,
          labelText: truncateLabel(ln.displayLabel, layout.maxLabelChars),
          numberText: null,
        });
        details.set(ln.id, {
          title: ln.displayLabel || label || ln.id,
          rows: buildRows(ln.node),
        });
        if (matched) matches.push({ x: ln.xPixel, y: ln.y });
        continue;
      }

      // Phylogeny
      if (ln.isLeaf) {
        let fill = "var(--foreground)";
        if (coloringEnabled && colorField) {
          const call = (anno?.[colorField] as string) || "";
          if (call && call !== "Germline" && call !== unknown) {
            const resolved = phyloColors[call] ?? "var(--foreground)";
            fill = isBlackColor(resolved) ? "var(--foreground)" : resolved;
          }
        }
        const displayLabel = resolveTipDisplayLabel(label, anno, displayIdField ?? null);
        const matched =
          !!needle &&
          (buildTipTitle(label, anno, colorField, displayIdField ?? null)
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
          labelShown: showLabels,
          labelText: truncateLabel(displayLabel, layout.maxLabelChars),
          numberText: null,
        });
        details.set(ln.id, buildTipRows(label, anno, displayIdField ?? null));
        if (matched) matches.push({ x: ln.xPixel, y: ln.y });
      } else {
        internalCount += 1;
        if (showInternalNodes) {
          out.push({
            id: ln.id,
            cx: ln.xPixel,
            cy: ln.y,
            r: PHYLO_INTERNAL_RADIUS,
            fill: "none",
            stroke: "currentColor",
            strokeWidth: 1.2,
            hollow: true,
            isMatch: false,
            labelShown: false,
            labelText: "",
            numberText: showNodeNumbers ? `#${internalCount}` : null,
          });
          details.set(ln.id, buildTipRows(label, anno, displayIdField ?? null));
        }
      }
    }

    const edgeVisuals: EdgeVisual[] = layout.edges.map((e) => ({
      key: e.key,
      d: `M ${e.sx} ${e.sy} L ${e.sx} ${e.ty} L ${e.tx} ${e.ty}`,
    }));

    return { visuals: out, edges: edgeVisuals, detailById: details, matchPoints: matches };
  }, [
    layout,
    isLineage,
    needle,
    displayIdField,
    showLabels,
    showInternalNodes,
    showNodeNumbers,
    coloringEnabled,
    colorField,
    unknown,
    phyloColors,
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
    // Re-fit only when the underlying tree changes (not on display toggles).
    fitKey: model,
  });

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

  if (!visuals.length) {
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
      <svg
        ref={setSvgEl}
        className="absolute inset-0 h-full w-full touch-none select-none"
        role="img"
      >
        <g transform={zoomApi.transform.toString()}>
          <SvgTreeRenderer
            nodes={visuals}
            edges={edges}
            transform={zoomApi.transform}
            lod="full"
            labelX={layout.labelX}
            connectorX={layout.connectorX}
            highlightText={highlightText ?? null}
            markMatches={markMatches}
            onNodeClick={(id) => setSelectedNode(detailById.get(id) ?? null)}
            onNodeContextMenu={() => {}}
          />
        </g>
      </svg>

      {/* Download (top-right) */}
      <div className="absolute right-3 top-3">
        <DownloadMenu
          formats={[
            {
              label: "PNG image",
              description: "Raster image of the whole tree",
              onSelect: () =>
                downloadPng(serializeTreeSvg(visuals, edges, meta), meta.width, meta.height, `${filename}.png`),
            },
            {
              label: "SVG image",
              description: "Scalable vector graphic",
              onSelect: () => downloadSvg(serializeTreeSvg(visuals, edges, meta), `${filename}.svg`),
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
