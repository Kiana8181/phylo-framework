import type { TreeNodeAttrs } from "@phylo/contracts";

/** Warning emitted while adapting a source into a TreeModel. Shape/codes are
 * preserved from the original LineageSVG `buildLayout`. */
export type LayoutWarning = {
  code: string;
  message: string;
  details?: Record<string, unknown>;
};

/** A phylogeny annotation row (as assembled today in TreesCarousel). The core
 * owns this type because `packages/contracts` intentionally does not define it. */
export type PhyloAnnotation = { label: string } & Record<string, unknown>;

/** Colour-by scale placeholder. Phase 4 fleshes this out (categorical /
 * continuous, legend domain, etc.). Phase 1 only needs the abundance ramp. */
export type ColorScale = {
  kind: "abundance";
  colorFor: (value: number) => string;
  domainMin: number;
  domainMax: number;
};

/** A single node in the renderer-agnostic tree model. Both adapters produce
 * this; all downstream code sees only TreeModel. See spec §3.2. */
export type TreeNodeModel = {
  id: string;
  label: string;
  parentId: string | null;
  childIds: string[];
  isLeaf: boolean;
  /** root = 0 */
  depth: number;
  /** Horizontal position in SOURCE units (mutation distance / branch length).
   * NEVER recomputed by rank. Transformed only by one shared affine map. */
  xSource: number;
  /** Server-provided vertical position. USED ONLY AS A SIBLING SORT KEY.
   * null for phylogeny (sibling order = newick order). */
  ySourceOrder: number | null;
  /** >= 1, existing toAbundance() semantics. */
  abundance: number;
  attrs: TreeNodeAttrs | undefined;
  // Aggregates for collapsed rendering, precomputed once per model.
  subtreeLeafCount: number;
  subtreeNodeCount: number;
  subtreeAbundanceSum: number;
  subtreeMaxX: number;
};

export type TreeModel = {
  rootId: string;
  nodes: ReadonlyMap<string, TreeNodeModel>;
  /** Stable DFS pre-order of all node ids. */
  order: readonly string[];
  warnings: LayoutWarning[];
};

/** A positioned node ready to render. Geometry only; display (colour, title,
 * rows) is derived by the renderer from `.node`. */
export type LayoutNode = {
  id: string;
  /** Pixel x after the single shared affine map. */
  xPixel: number;
  /** Pixel y from client-side variable-height packing. */
  y: number;
  radius: number;
  isLeaf: boolean;
  /** Resolved display label (already respects display options). */
  displayLabel: string;
  /** Whether this node's label is drawn (leaf+showLabels or internal+showInternalNodes). */
  labelShown: boolean;
  /** True when this node is a collapsed-subtree root (drawn as a triangle glyph). */
  isCollapsed: boolean;
  /** Far x (pixels) of the collapsed wedge = subtreeMaxX through the shared kx. */
  glyphFarXPixel?: number;
  /** Half-height (pixels) of the collapsed wedge. */
  glyphHalfHeight?: number;
  node: TreeNodeModel;
};

/** A rectangular-cladogram elbow edge: `M sx sy L sx ty L tx ty`. */
export type LayoutEdge = {
  key: string;
  sx: number;
  sy: number;
  tx: number;
  ty: number;
};

export type TreeLayout = {
  nodes: LayoutNode[];
  edges: LayoutEdge[];
  width: number;
  height: number;
  /** Shared x column where labels start (0 when labels hidden). */
  labelX: number;
  /** x where connector lines stop, just left of the label column. */
  connectorX: number;
  maxLabelChars: number;
  /** Abundance extent used for radius; reused by the renderer for colour so the
   * two channels agree. */
  abundanceMin: number;
  abundanceMax: number;
  warnings: LayoutWarning[];
};
