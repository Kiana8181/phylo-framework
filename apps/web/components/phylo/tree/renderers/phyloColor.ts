// Phylogeny colour-by-field helpers. Moved VERBATIM from TreeSVG (Phase 1 kept
// them local). Behaviour is unchanged — Phase 4 folds these into
// core/colorScale.ts with continuous/categorical detection, an explicit shared
// domain, and a legend. Until then this is the single home for phylogeny colour.

import type { PhyloAnnotation } from "@/components/phylo/tree/core";

type Anno = PhyloAnnotation;

const GOLDEN_ANGLE = 137.50776405003785;
const SAT_BANDS = [74, 62, 82, 55] as const;
const LIG_BANDS = [45, 58, 36, 66] as const;

export function colorByIndex(k: number): string {
  const hue = (k * GOLDEN_ANGLE) % 360;
  const sat = SAT_BANDS[k % SAT_BANDS.length];
  const lig = LIG_BANDS[Math.floor(k / SAT_BANDS.length) % LIG_BANDS.length];
  return `hsl(${hue.toFixed(3)}, ${sat}%, ${lig}%)`;
}

export function buildColorMapDistinct(
  list: Anno[] | undefined,
  field: string | null,
  unknownValue: string,
): Record<string, string> {
  const map: Record<string, string> = {};
  if (!list?.length || !field) return map;

  const set = new Set<string>();
  for (const a of list) {
    const v = a?.[field];
    if (typeof v === "string") {
      const vv = v.trim();
      if (vv && vv !== "Germline" && vv !== unknownValue) {
        set.add(vv);
      }
    }
  }
  const values = Array.from(set).sort((a, b) => a.localeCompare(b, "en"));

  values.forEach((v, i) => {
    map[v] = colorByIndex(i);
  });

  map["Germline"] = "#000000";
  map[unknownValue] = "#000000";
  return map;
}

export function isBlackColor(value: string): boolean {
  const c = value.trim().toLowerCase();
  if (!c) return false;
  if (c === "black" || c === "#000" || c === "#000000" || c === "#000000ff") return true;

  const rgb = c.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const parts = rgb[1].split(",").map((v) => Number(v.trim()));
    if (parts.length >= 3) {
      const [r, g, b] = parts;
      return r === 0 && g === 0 && b === 0;
    }
  }

  return false;
}
