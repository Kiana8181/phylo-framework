import { clamp, logNorm } from "./math";
import { MAX_CATEGORIES, CONTINUOUS_MIN_DISTINCT } from "./constants";
import type { ColorScale, ColorLegendEntry, TreeModel, TreeNodeModel } from "./types";

// Viridis-like 10-stop ramp, ported verbatim from LineageSVG. Reused for the
// abundance ramp AND any other continuous numeric field.
export const ABUNDANCE_PALETTE = [
  "#440154",
  "#482878",
  "#3E4A89",
  "#31688E",
  "#26828E",
  "#1F9E89",
  "#35B779",
  "#6CCE59",
  "#B4DD2C",
  "#FDE725",
] as const;

/** Map an abundance value to a palette colour (log-normalised). Verbatim port. */
export function colorForAbundance(value: number, min: number, max: number): string {
  const t = logNorm(value, min, max);
  const idx = Math.round(t * (ABUNDANCE_PALETTE.length - 1));
  return ABUNDANCE_PALETTE[clamp(idx, 0, ABUNDANCE_PALETTE.length - 1)];
}

// Okabe–Ito colourblind-safe qualitative palette (8). The original black is
// swapped for a theme-safe mid-grey so it survives dark mode.
const OKABE_ITO = [
  "#E69F00",
  "#56B4E9",
  "#009E73",
  "#F0E442",
  "#0072B2",
  "#D55E00",
  "#CC79A7",
  "#767676",
] as const;

const UNKNOWN_COLOR = "var(--tree-node-unknown)";
const GERMLINE_COLOR = "var(--tree-germline)";
const NEUTRAL_COLOR = "var(--foreground)";
const OTHER_COLOR = "oklch(0.6 0.03 285)"; // neutral, distinct from unknown
const DEFAULT_GERMLINE_LABEL = "Germline";

/** Evenly-spaced OKLCH hues with alternating lightness/chroma bands (spec §4.2). */
function oklchPalette(n: number): string[] {
  const h0 = 25;
  const L = [0.62, 0.48];
  const C = [0.16, 0.11];
  const out: string[] = [];
  for (let i = 0; i < n; i++) {
    const h = (h0 + (i * 360) / n) % 360;
    const l = L[i % 2];
    const c = C[Math.floor(i / 2) % 2];
    out.push(`oklch(${l} ${c} ${h.toFixed(2)})`);
  }
  return out;
}

/** distinct <= 8 → Okabe–Ito; else generated OKLCH. */
function categoricalPalette(n: number): string[] {
  if (n <= OKABE_ITO.length) return OKABE_ITO.slice(0, n);
  return oklchPalette(n);
}

/**
 * The colour-by field options = the field-key union of node attributes + phylo
 * annotations (excluding tooltip/label/final_tip_label), sequence_id first. This
 * is the SAME union `TreesCarousel` uses for its Display-ID options — one source.
 */
export function collectColorFields(
  nodeAttributes: Record<string, Record<string, unknown>> | undefined,
  phyloAnnotations: ReadonlyArray<Record<string, unknown>>,
): string[] {
  const keys = new Set<string>();
  for (const v of Object.values(nodeAttributes ?? {})) {
    if (!v || typeof v !== "object") continue;
    for (const key of Object.keys(v)) {
      if (key === "tooltip") continue;
      keys.add(key);
    }
  }
  for (const row of phyloAnnotations) {
    for (const [key, value] of Object.entries(row)) {
      if (key === "label" || key === "final_tip_label") continue;
      if (value != null && value !== "") keys.add(key);
    }
  }
  const options = Array.from(keys).sort((a, b) => a.localeCompare(b, "en"));
  return options.includes("sequence_id")
    ? ["sequence_id", ...options.filter((k) => k !== "sequence_id")]
    : options;
}

export type BuildColorScaleOptions = {
  /** Cross-panel domain: the union of values across sibling panels, so a value
   * maps to one colour everywhere. Single-tree callers pass null. */
  explicitValues?: readonly string[] | null;
  germlineLabel?: string;
  unknownValue?: string;
};

function noneScale(): ColorScale {
  return {
    field: null,
    kind: "none",
    colorFor: () => NEUTRAL_COLOR,
    unknownColor: UNKNOWN_COLOR,
    germlineColor: GERMLINE_COLOR,
    hasUnknown: false,
    legend: { kind: "none" },
  };
}

/**
 * Build the colour encoding for a field. `abundance` is always continuous (and
 * reproduces `colorForAbundance` exactly). Other fields are auto-detected as
 * continuous (≥90% numeric AND > CONTINUOUS_MIN_DISTINCT distinct) or categorical.
 * Germline is excluded from the categorical domain and gets its own token.
 */
export function buildColorScale(
  model: TreeModel,
  field: string | null,
  opts: BuildColorScaleOptions = {},
): ColorScale {
  if (!field || field === "none") return noneScale();

  const germlineLabel = (opts.germlineLabel || DEFAULT_GERMLINE_LABEL).trim();
  const unknownValue = (opts.unknownValue || "").trim();
  const isGermline = (v: string) => v === germlineLabel;
  const isUnknown = (v: string) => !v || (!!unknownValue && v === unknownValue);

  // Abundance: continuous over the model's extent (byte-identical to before).
  if (field === "abundance") {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const n of model.nodes.values()) {
      if (n.abundance < min) min = n.abundance;
      if (n.abundance > max) max = n.abundance;
    }
    if (!Number.isFinite(min)) {
      min = 1;
      max = 1;
    }
    return {
      field,
      kind: "continuous",
      colorFor: (n) => colorForAbundance(n.abundance, min, max),
      unknownColor: UNKNOWN_COLOR,
      germlineColor: GERMLINE_COLOR,
      hasUnknown: false,
      legend: { kind: "continuous", min, max, ramp: ABUNDANCE_PALETTE },
    };
  }

  const valueOf = (n: TreeNodeModel) => String(n.attrs?.[field] ?? "").trim();

  // Gather this model's values (for counts) + whether anything is missing.
  const modelValues: string[] = [];
  let hasUnknown = false;
  for (const n of model.nodes.values()) {
    const v = valueOf(n);
    if (isGermline(v)) continue; // germline excluded from domain
    if (isUnknown(v)) {
      hasUnknown = true;
      continue;
    }
    modelValues.push(v);
  }

  // Domain source: the explicit cross-panel union when given, else this model.
  const domainSource = (
    opts.explicitValues && opts.explicitValues.length
      ? opts.explicitValues.map((v) => String(v).trim())
      : modelValues
  ).filter((v) => v && !isGermline(v) && !isUnknown(v));

  // Type detection.
  const distinct = new Set(domainSource);
  const numericCount = domainSource.filter((v) => Number.isFinite(Number(v))).length;
  const continuous =
    domainSource.length > 0 &&
    numericCount / domainSource.length >= 0.9 &&
    distinct.size > CONTINUOUS_MIN_DISTINCT;

  if (continuous) {
    let min = Number.POSITIVE_INFINITY;
    let max = Number.NEGATIVE_INFINITY;
    for (const v of domainSource) {
      const num = Number(v);
      if (Number.isFinite(num)) {
        if (num < min) min = num;
        if (num > max) max = num;
      }
    }
    if (!Number.isFinite(min)) {
      min = 0;
      max = 1;
    }
    const colorForNum = (x: number) => {
      const t = max > min ? clamp((x - min) / (max - min), 0, 1) : 0;
      return ABUNDANCE_PALETTE[clamp(Math.round(t * (ABUNDANCE_PALETTE.length - 1)), 0, ABUNDANCE_PALETTE.length - 1)];
    };
    return {
      field,
      kind: "continuous",
      colorFor: (n) => {
        const v = valueOf(n);
        if (isGermline(v)) return GERMLINE_COLOR;
        const num = Number(v);
        if (isUnknown(v) || !Number.isFinite(num)) return UNKNOWN_COLOR;
        return colorForNum(num);
      },
      unknownColor: UNKNOWN_COLOR,
      germlineColor: GERMLINE_COLOR,
      hasUnknown,
      legend: { kind: "continuous", min, max, ramp: ABUNDANCE_PALETTE },
    };
  }

  // Categorical. Counts from THIS model (for legend + frequency bucketing).
  const counts = new Map<string, number>();
  for (const v of modelValues) counts.set(v, (counts.get(v) ?? 0) + 1);

  const sortedDistinct = Array.from(distinct).sort((a, b) => a.localeCompare(b, "en"));
  let kept = sortedDistinct;
  let hasOther = false;
  if (sortedDistinct.length > MAX_CATEGORIES) {
    hasOther = true;
    if (opts.explicitValues && opts.explicitValues.length) {
      // Cross-panel: deterministic by sort order so every panel agrees.
      kept = sortedDistinct.slice(0, MAX_CATEGORIES - 1);
    } else {
      // Single panel: keep the most frequent, then sort for a stable index.
      kept = [...sortedDistinct]
        .sort((a, b) => (counts.get(b) ?? 0) - (counts.get(a) ?? 0))
        .slice(0, MAX_CATEGORIES - 1)
        .sort((a, b) => a.localeCompare(b, "en"));
    }
  }
  const keptIndex = new Map(kept.map((v, i) => [v, i]));
  const palette = categoricalPalette(kept.length);
  const colorForValue = (v: string) => {
    const idx = keptIndex.get(v);
    return idx == null ? OTHER_COLOR : palette[idx];
  };

  // Legend: only values present in THIS model (count > 0), plus Other/unknown.
  const entries: ColorLegendEntry[] = [];
  let otherCount = 0;
  for (const [v, n] of counts) {
    if (keptIndex.has(v)) entries.push({ key: v, label: v, color: colorForValue(v), count: n });
    else otherCount += n;
  }
  entries.sort((a, b) => a.label.localeCompare(b.label, "en"));
  if (hasOther && otherCount > 0) {
    entries.push({ key: "__other__", label: `Other (n=${otherCount})`, color: OTHER_COLOR, count: otherCount });
  }

  return {
    field,
    kind: "categorical",
    colorFor: (n) => {
      const v = valueOf(n);
      if (isGermline(v)) return GERMLINE_COLOR;
      if (isUnknown(v)) return UNKNOWN_COLOR;
      return colorForValue(v);
    },
    unknownColor: UNKNOWN_COLOR,
    germlineColor: GERMLINE_COLOR,
    hasUnknown,
    legend: { kind: "categorical", entries },
  };
}
