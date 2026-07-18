import type { ReactNode } from "react";
import type { ZoomTransform } from "d3-zoom";
import type { NodeVisual, EdgeVisual, GlyphVisual } from "@/components/phylo/tree/core";

/** Semantic-zoom level of detail (Phase 3), driven by `transform.k`. */
export type LodLevel = "dots" | "nodes" | "full";

export type TreeRenderProps = {
  /** Fully-resolved, layout-derived visuals (already culled in Phase 6; identity
   * before then). Shared with the export serialiser so both draw the same thing. */
  nodes: readonly NodeVisual[];
  edges: readonly EdgeVisual[];
  /** Collapsed-subtree wedges. */
  glyphs: readonly GlyphVisual[];
  /** Current zoom transform (applied by the parent to the wrapping `<g>`). */
  transform: ZoomTransform;
  /** Semantic-zoom level from `transform.k`. */
  lod: LodLevel;
  /** Shared label-column geometry from the layout. */
  labelX: number;
  connectorX: number;
  /** Sequence-Trace search text (drives label sub-highlighting). */
  highlightText: string | null;
  /** Draw "Show me" arrows over matched nodes. */
  markMatches: boolean;
  onNodeClick: (id: string) => void;
  /** Collapse/expand toggle (right-click, chevron, glyph click, Space, long-press). */
  onToggleCollapse: (id: string) => void;
};

/**
 * The renderer seam. Only the SVG renderer exists.
 *
 * // TODO(canvas): a CanvasTreeRenderer implementing this same interface is the
 * // future perf option (spec §6.3). Do NOT implement it until a real
 * // measurement earns it — genotype-collapsed BCR trees don't reach that scale.
 */
export type TreeRenderer = (props: TreeRenderProps) => ReactNode;
