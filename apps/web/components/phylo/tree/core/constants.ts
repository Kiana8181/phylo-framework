// Every tunable for the tree core, one file. One short comment each.
// Phase 1 uses the layout/label/radius constants; the rest are declared here so
// later phases (collapse, zoom LOD, colour, minimap, culling) only flip values.

export const ROW_GAP = 6; // vertical gap between adjacent packed slots (px)
export const PAD = 24; // outer padding around the content bbox (px)

// Node radius (preserved from LineageSVG; now shared by both views).
export const MIN_RADIUS = 3;
export const MAX_RADIUS = 24;

// Labels (preserved verbatim from LineageSVG).
export const LABEL_FONT_SIZE = 11;
export const LABEL_PAD = 10; // gap between plot right edge and the label column
export const LABEL_CONNECTOR_GAP = 4; // gap between label and its connector line
export const LABEL_CHAR_WIDTH = 6.8; // px/char used to estimate label column width
export const MIN_LABEL_AREA = 40; // min label column width (px)
export const MAX_LABEL_AREA = 120; // max label column width (px)

// The lineage renderer historically scaled coords so the plot filled ~960x520.
// We keep the width target as the single affine x-map's fill width (Phase 2
// replaces this with a measured container width via ResizeObserver).
export const TARGET_PLOT_WIDTH = 960;

// Minimum on-screen content size for the (Phase-1) scroll containers. These are
// scroll-era hacks slated for removal in Phase 2 alongside the scroll containers.
export const MIN_CONTENT_WIDTH = 920;
export const MIN_CONTENT_HEIGHT = 300;

// Collapsed-glyph height envelope (Phase 3). Declared now so layout's rowExtent
// can account for it; in Phase 1 no node is collapsed so it never contributes.
export const COLLAPSED_GLYPH_MIN_H = 10;
export const COLLAPSED_GLYPH_MAX_H = 48;

// ---- Later-phase tunables (declared for §7 completeness; unused in Phase 1) ----
export const DEFAULT_COLLAPSE_DEPTH = 3; // Phase 3: auto-collapse depth
export const AUTO_COLLAPSE_MIN_NODES = 150; // Phase 3: 0 = always auto-collapse
export const CULL_MIN_NODES = 400; // Phase 6: below this, culling costs more than it saves
export const MINIMAP_MIN_NODES = 60; // Phase 6: below this, a minimap is noise
export const LOD_LABELS_K = 0.6; // Phase 3: zoom at/above which chevrons + node numbers show
// Below this zoom the tree renders as a compact overview (tiny dots, no text).
// Kept low so the narrow Sequence-Trace panels (which fit at small k) still show
// a complete tree with labels; genuine overview "dots" only at extreme zoom-out.
export const LOD_DETAIL_K = 0.12; // Phase 3: zoom below which nodes become dots
export const FOCUS_SCALE = 2.5; // Phase 2: zoom applied on "Show me" (ported from CompareExpandDialog)
export const MAX_CATEGORIES = 20; // Phase 4: categorical palette cap
export const CONTINUOUS_MIN_DISTINCT = 8; // Phase 4: numeric-field continuous threshold
export const CANVAS_WARN_NODES = 3000; // Phase 6: dev warn threshold at the renderer seam
