// Full-tree export. CRITICAL (spec §2.5): this serialises the full, un-culled
// layout at the current collapse state — never "whatever is on screen". It works
// from the layout-derived `NodeVisual[]`/`EdgeVisual[]` (not the DOM), so Phase 6
// culling can never leak into exports. The interactive SvgTreeRenderer consumes
// the SAME visuals array, so there is one source of truth for "what to draw".

import { LABEL_FONT_SIZE } from "./constants";

/** A fully-resolved node ready to draw — shared by the React renderer and the
 * export serialiser. Geometry + colour + label; framework-agnostic plain data. */
export type NodeVisual = {
  id: string;
  cx: number;
  cy: number;
  r: number;
  /** Base fill (may be `var(--foreground)` for theme-aware on-screen rendering). */
  fill: string;
  stroke: string | null;
  strokeWidth: number;
  /** Phylogeny internal node: hollow ring (no fill), stroke = currentColor. */
  hollow: boolean;
  /** Matched by the Sequence-Trace search predicate. */
  isMatch: boolean;
  /** Highlighted via a legend-entry click → drawn with a ring. */
  ringed: boolean;
  /** Expanded internal node with children → shows a collapse chevron (render hint). */
  isCollapsible: boolean;
  labelShown: boolean;
  /** Already truncated to the label column width. */
  labelText: string;
  /** Phylogeny internal node number ("#n") when node numbers are on. */
  numberText: string | null;
};

/** A precomputed elbow edge path (`M sx sy L sx ty L tx ty`). */
export type EdgeVisual = { key: string; d: string };

/** A collapsed-subtree wedge (triangle), apex at the node, base at `farX`. */
export type GlyphVisual = {
  id: string;
  apexX: number;
  y: number;
  farX: number;
  halfHeight: number;
  fill: string;
  /** Aggregate of multiple distinct colour values → hatched/translucent. */
  striped: boolean;
  isMatch: boolean;
  /** e.g. "n=12  Σ=340" (already composed); null when labels are off. */
  labelText: string | null;
};

export type TreeSvgMeta = {
  width: number;
  height: number;
  labelX: number;
  connectorX: number;
  strokeWidth: number;
};

const MATCH_FILL = "#dc2626";
// Export is rasterised/saved without the app's CSS context, so `currentColor` /
// `var(--foreground)` would not resolve. Substitute a concrete dark ink.
const EXPORT_INK = "#111827";

function xmlEscape(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function exportColor(c: string): string {
  const v = c.trim();
  if (v === "currentColor" || v.startsWith("var(")) return EXPORT_INK;
  return v;
}

/**
 * Serialise the full tree to a standalone SVG string at natural size. Pure and
 * unit-testable; independent of any zoom transform. Contains every node in
 * `nodes` (the un-culled invariant).
 */
export function serializeTreeSvg(
  nodes: readonly NodeVisual[],
  edges: readonly EdgeVisual[],
  meta: TreeSvgMeta,
  glyphs: readonly GlyphVisual[] = [],
): string {
  const parts: string[] = [];
  parts.push(
    `<svg xmlns="http://www.w3.org/2000/svg" width="${meta.width}" height="${meta.height}" ` +
      `viewBox="0 0 ${meta.width} ${meta.height}" style="background:#ffffff;color:${EXPORT_INK}">`,
  );

  // Edges.
  parts.push(
    `<g fill="none" stroke="${EXPORT_INK}" stroke-width="${meta.strokeWidth}" opacity="0.8">`,
  );
  for (const e of edges) parts.push(`<path d="${e.d}"/>`);
  parts.push(`</g>`);

  // Collapsed-subtree wedges.
  for (const g of glyphs) {
    const fill = exportColor(g.isMatch ? MATCH_FILL : g.fill);
    parts.push(
      `<path d="M ${g.apexX} ${g.y} L ${g.farX} ${g.y - g.halfHeight} L ${g.farX} ${g.y + g.halfHeight} Z" ` +
        `fill="${fill}" fill-opacity="${g.striped ? 0.5 : 0.9}" stroke="${EXPORT_INK}" stroke-width="0.75"/>`,
    );
    if (g.labelText) {
      parts.push(
        `<text x="${g.farX + 6}" y="${g.y}" dominant-baseline="middle" font-size="${LABEL_FONT_SIZE}" fill="${EXPORT_INK}">${xmlEscape(g.labelText)}</text>`,
      );
    }
  }

  // Nodes.
  parts.push(`<g>`);
  for (const n of nodes) {
    const fill = n.hollow ? "none" : exportColor(n.isMatch ? MATCH_FILL : n.fill);
    const stroke = n.hollow ? EXPORT_INK : n.isMatch ? "#b91c1c" : n.stroke ? exportColor(n.stroke) : "none";
    const sw = n.hollow ? 1.2 : n.strokeWidth;
    parts.push(
      `<circle cx="${n.cx}" cy="${n.cy}" r="${n.r}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}"/>`,
    );
    if (n.numberText) {
      parts.push(
        `<text x="${n.cx + 6}" y="${n.cy - 6}" font-size="9" fill="${EXPORT_INK}" opacity="0.8">${xmlEscape(n.numberText)}</text>`,
      );
    }
  }
  parts.push(`</g>`);

  // Labels (drawn in the shared right-hand column, matching the on-screen layout).
  const labelNodes = nodes.filter((n) => n.labelShown && n.labelText);
  if (labelNodes.length) {
    parts.push(`<g font-size="${LABEL_FONT_SIZE}" fill="${EXPORT_INK}">`);
    for (const n of labelNodes) {
      parts.push(
        `<line x1="${n.cx}" y1="${n.cy}" x2="${meta.connectorX}" y2="${n.cy}" stroke="${EXPORT_INK}" stroke-width="0.5" opacity="0.4"/>`,
      );
      const fill = n.isMatch ? MATCH_FILL : EXPORT_INK;
      parts.push(
        `<text x="${meta.labelX}" y="${n.cy}" dominant-baseline="middle" fill="${fill}">${xmlEscape(n.labelText)}</text>`,
      );
    }
    parts.push(`</g>`);
  }

  parts.push(`</svg>`);
  return parts.join("");
}

function triggerDownload(href: string, filename: string, revoke = false): void {
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  if (revoke) URL.revokeObjectURL(href);
}

export function downloadSvg(svgMarkup: string, filename: string): void {
  const blob = new Blob([svgMarkup], { type: "image/svg+xml;charset=utf-8" });
  triggerDownload(URL.createObjectURL(blob), filename, true);
}

export function downloadPng(
  svgMarkup: string,
  width: number,
  height: number,
  filename: string,
): void {
  const img = new Image();
  img.onload = () => {
    const canvas = document.createElement("canvas");
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.fillStyle = "white";
    ctx.fillRect(0, 0, width, height);
    ctx.drawImage(img, 0, 0);
    triggerDownload(canvas.toDataURL("image/png"), filename);
  };
  img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgMarkup)}`;
}

export function downloadNewick(text: string, filename: string): void {
  const trimmed = text.trim();
  const normalized = trimmed.endsWith(";") ? trimmed : `${trimmed};`;
  const blob = new Blob([normalized], { type: "text/plain" });
  triggerDownload(URL.createObjectURL(blob), filename, true);
}
