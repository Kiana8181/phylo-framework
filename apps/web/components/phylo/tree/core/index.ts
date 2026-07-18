// Public surface of the tree core. React lives at the edges; everything here is
// framework-light and unit-testable.
export * from "./types";
export * from "./constants";
export { clamp, isFiniteNumber, toAbundance, logNorm, linNorm } from "./math";
export { truncateLabel, estimateTextWidth, splitByHighlight } from "./text";
export { nodeRadius, type RadiusScaleType } from "./nodeRadius";
export { ABUNDANCE_PALETTE, colorForAbundance, buildAbundanceScale } from "./colorScale";
export { fromLineagePlot } from "./fromLineagePlot";
export { fromNewick, sanitizeNewick, type FromNewickOptions } from "./fromNewick";
export { layoutTree, type LayoutOptions } from "./layout";
export {
  defaultCollapsed,
  collapseAll,
  expandAll,
  toggleCollapse,
  subtreeColorSummary,
  type ColorKey,
} from "./collapse";
export {
  resolveDisplayLabel,
  resolveNodeDisplayLabel,
  buildTitle,
  buildRows,
  type DetailRow,
} from "./lineageDisplay";
export {
  buildAnnoLookup,
  resolveAnno,
  buildTipTitle,
  buildTipRows,
  resolveTipDisplayLabel,
} from "./phyloDisplay";
export {
  serializeTreeSvg,
  downloadSvg,
  downloadPng,
  downloadNewick,
  type NodeVisual,
  type EdgeVisual,
  type GlyphVisual,
  type TreeSvgMeta,
} from "./download";
