import type { LayoutEdge, LayoutNode, TreeLayout, TreeModel, TreeNodeModel } from "./types";
import { nodeRadius, type RadiusScaleType } from "./nodeRadius";
import { clamp } from "./math";
import {
  ROW_GAP,
  PAD,
  LABEL_FONT_SIZE,
  LABEL_PAD,
  LABEL_CONNECTOR_GAP,
  LABEL_CHAR_WIDTH,
  MIN_LABEL_AREA,
  MAX_LABEL_AREA,
  TARGET_PLOT_WIDTH,
  MIN_CONTENT_WIDTH,
  MIN_CONTENT_HEIGHT,
  COLLAPSED_GLYPH_MIN_H,
  COLLAPSED_GLYPH_MAX_H,
} from "./constants";

export type LayoutOptions = {
  /** Collapsed node ids (Phase 3). Always empty in Phase 1. */
  collapsed?: ReadonlySet<string>;
  /** Radius scale. Default log1p for both views (signed-off, spec §1.4). */
  scaleType?: RadiusScaleType;
  showLabels: boolean;
  showInternalNodes: boolean;
  /** Resolve the display label for a node (respects current display options). */
  displayLabelOf: (node: TreeNodeModel) => string;
  /** Width the single affine x-map fills. Phase 2 feeds a measured width. */
  targetWidth?: number;
};

const EMPTY_COLLAPSE: ReadonlySet<string> = new Set();

function emptyLayout(warnings: TreeLayout["warnings"]): TreeLayout {
  return {
    nodes: [],
    edges: [],
    width: MIN_CONTENT_WIDTH,
    height: MIN_CONTENT_HEIGHT,
    labelX: 0,
    connectorX: 0,
    maxLabelChars: 1,
    abundanceMin: 1,
    abundanceMax: 1,
    warnings,
  };
}

/** Collapsed-triangle glyph height ~ log1p(leafCount), clamped. Phase 3 uses it;
 * in Phase 1 no node is collapsed so it never contributes to packing. */
function collapsedGlyphHeight(leafCount: number): number {
  return clamp(Math.log1p(leafCount) * 12, COLLAPSED_GLYPH_MIN_H, COLLAPSED_GLYPH_MAX_H);
}

/**
 * Collapse-aware layout. Assigns pixel y via variable-height cumulative packing
 * of visible terminal slots, maps xSource through a single shared affine map,
 * and emits rectangular-cladogram elbow edges. Pure and unit-testable.
 */
export function layoutTree(model: TreeModel, opts: LayoutOptions): TreeLayout {
  if (model.nodes.size === 0 || !model.nodes.has(model.rootId)) {
    return emptyLayout(model.warnings);
  }

  const collapsed = opts.collapsed ?? EMPTY_COLLAPSE;
  const scaleType = opts.scaleType ?? "log1p";
  const targetWidth = opts.targetWidth ?? TARGET_PLOT_WIDTH;
  const { showLabels, showInternalNodes } = opts;

  // Abundance extent across the whole model (matches the original renderers,
  // which sized against all nodes, not just the visible subset).
  let abundanceMin = Number.POSITIVE_INFINITY;
  let abundanceMax = Number.NEGATIVE_INFINITY;
  for (const node of model.nodes.values()) {
    if (node.abundance < abundanceMin) abundanceMin = node.abundance;
    if (node.abundance > abundanceMax) abundanceMax = node.abundance;
  }
  if (!Number.isFinite(abundanceMin)) abundanceMin = 1;
  if (!Number.isFinite(abundanceMax)) abundanceMax = 1;

  const radiusOf = (node: TreeNodeModel) =>
    nodeRadius(node.abundance, abundanceMin, abundanceMax, scaleType);

  // 1) Stable sibling order by ySourceOrder (nulls/ties keep input order).
  const sortedChildrenCache = new Map<string, string[]>();
  const sortedChildren = (node: TreeNodeModel): string[] => {
    const cached = sortedChildrenCache.get(node.id);
    if (cached) return cached;
    const ids = node.childIds.slice();
    ids.sort((aId, bId) => {
      const a = model.nodes.get(aId)?.ySourceOrder;
      const b = model.nodes.get(bId)?.ySourceOrder;
      if (a == null || b == null) return 0; // keep input order (stable sort)
      return a - b;
    });
    sortedChildrenCache.set(node.id, ids);
    return ids;
  };

  // 2) Visible traversal honouring collapse. Terminal slots get a y; collapsed
  //    and childless nodes are terminal. Records visible node ids in order.
  const slotIds: string[] = [];
  const visibleIds: string[] = [];
  const isTerminal = (node: TreeNodeModel) =>
    collapsed.has(node.id) || node.childIds.length === 0;

  const walk = (id: string) => {
    const node = model.nodes.get(id);
    if (!node) return;
    visibleIds.push(id);
    if (isTerminal(node)) {
      slotIds.push(id);
      return;
    }
    for (const childId of sortedChildren(node)) walk(childId);
  };
  walk(model.rootId);

  // 3) Variable-height cumulative packing of terminal slots.
  const rowExtent = (node: TreeNodeModel): number => {
    const glyphHalf = collapsed.has(node.id)
      ? collapsedGlyphHeight(node.subtreeLeafCount) / 2
      : 0;
    return Math.max(radiusOf(node), LABEL_FONT_SIZE / 2, glyphHalf);
  };

  const yById = new Map<string, number>();
  let prevY = 0;
  let prevExtent = 0;
  slotIds.forEach((id, i) => {
    const node = model.nodes.get(id)!;
    const ext = rowExtent(node);
    const y = i === 0 ? PAD + ext : prevY + prevExtent + ROW_GAP + ext;
    yById.set(id, y);
    prevY = y;
    prevExtent = ext;
  });

  // 4) Internal node y = midpoint of first & last visible child (post-order).
  const resolveY = (id: string): number => {
    const cached = yById.get(id);
    if (cached != null) return cached;
    const node = model.nodes.get(id)!;
    const kids = sortedChildren(node);
    const firstY = resolveY(kids[0]);
    const lastY = resolveY(kids[kids.length - 1]);
    const y = (firstY + lastY) / 2;
    yById.set(id, y);
    return y;
  };
  for (const id of visibleIds) resolveY(id);

  // 5) Single shared affine x-map over the FULL model (not just the visible set)
  //    so collapsing far nodes never shifts any node's xPixel — the x-axis is a
  //    scientific coordinate and must be collapse-invariant (spec §3, acceptance).
  let xSourceMin = Number.POSITIVE_INFINITY;
  let xSourceMax = Number.NEGATIVE_INFINITY;
  for (const node of model.nodes.values()) {
    if (node.xSource < xSourceMin) xSourceMin = node.xSource;
    if (node.xSource > xSourceMax) xSourceMax = node.xSource;
  }
  // Scale so the source x-range fills targetWidth. Guard only against a zero
  // span (single node, or all nodes at the same x) — do NOT clamp the divisor
  // to 1: branch-length trees span < 1 total, and clamping would crush them.
  const xRange = xSourceMax - xSourceMin;
  const kx = xRange > 0 ? targetWidth / xRange : 0;
  const xFromSource = (xSource: number) => (xSource - xSourceMin) * kx + PAD;
  const xPixelOf = (node: TreeNodeModel) => xFromSource(node.xSource);

  // 6) Build layout nodes (collapsed nodes carry their wedge geometry).
  const nodes: LayoutNode[] = visibleIds.map((id) => {
    const node = model.nodes.get(id)!;
    const displayLabel = opts.displayLabelOf(node);
    const labelShown =
      (node.isLeaf && showLabels) || (!node.isLeaf && showInternalNodes);
    const isCollapsed = collapsed.has(id) && node.childIds.length > 0;
    return {
      id,
      xPixel: xPixelOf(node),
      y: yById.get(id)!,
      radius: radiusOf(node),
      isLeaf: node.isLeaf,
      displayLabel,
      labelShown,
      isCollapsed,
      glyphFarXPixel: isCollapsed ? xFromSource(node.subtreeMaxX) : undefined,
      glyphHalfHeight: isCollapsed
        ? collapsedGlyphHeight(node.subtreeLeafCount) / 2
        : undefined,
      node,
    };
  });
  const nodeById = new Map(nodes.map((n) => [n.id, n]));

  // 7) Elbow edges: parent -> each visible child (skip collapsed subtrees).
  const edges: LayoutEdge[] = [];
  for (const parent of nodes) {
    const model_ = parent.node;
    if (collapsed.has(parent.id) || model_.childIds.length === 0) continue;
    for (const childId of sortedChildren(model_)) {
      const child = nodeById.get(childId);
      if (!child) continue;
      edges.push({
        key: `${parent.id}->${childId}`,
        sx: parent.xPixel,
        sy: parent.y,
        tx: child.xPixel,
        ty: child.y,
      });
    }
  }

  // 8) Label column geometry (against the visible, label-shown set).
  const labelsOn = showLabels || showInternalNodes;
  const shownLabels = nodes.filter((n) => n.labelShown).map((n) => n.displayLabel);
  const maxChars = shownLabels.length
    ? Math.max(...shownLabels.map((l) => l.length))
    : 0;
  const labelWidth = clamp(maxChars * LABEL_CHAR_WIDTH, MIN_LABEL_AREA, MAX_LABEL_AREA);
  const maxLabelChars = Math.max(1, Math.floor(labelWidth / LABEL_CHAR_WIDTH));

  // 9) Bounds (include collapsed wedges so they are never clipped).
  let plotRightX = Number.NEGATIVE_INFINITY;
  let maxY = Number.NEGATIVE_INFINITY;
  for (const n of nodes) {
    const rightX = n.isCollapsed ? (n.glyphFarXPixel ?? n.xPixel) : n.xPixel + n.radius;
    if (rightX > plotRightX) plotRightX = rightX;
    const ext = n.isCollapsed ? (n.glyphHalfHeight ?? 0) : rowExtent(n.node);
    if (n.y + ext > maxY) maxY = n.y + ext;
  }
  const labelX = labelsOn ? plotRightX + LABEL_PAD : 0;
  const connectorX = labelsOn ? Math.round(labelX) - LABEL_CONNECTOR_GAP : 0;
  const labelAreaWidth = labelsOn ? LABEL_PAD + labelWidth : 0;
  const width = Math.ceil(Math.max(MIN_CONTENT_WIDTH, plotRightX + labelAreaWidth + PAD));
  const height = Math.ceil(Math.max(MIN_CONTENT_HEIGHT, maxY + PAD));

  return {
    nodes,
    edges,
    width,
    height,
    labelX: Math.round(labelX),
    connectorX,
    maxLabelChars,
    abundanceMin,
    abundanceMax,
    warnings: model.warnings,
  };
}
