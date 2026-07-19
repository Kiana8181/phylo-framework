import { describe, it, expect } from "vitest";
import { nodeRadius } from "../nodeRadius";
import { colorForAbundance, ABUNDANCE_PALETTE } from "../colorScale";

/**
 * Contract snapshot for Phase 4: the abundance radius/colour must remain
 * byte-identical to the original LineageSVG behaviour. The reference formulas
 * below are copied verbatim from the pre-refactor renderer; if the core ever
 * diverges, these fail.
 */
function refClamp(v: number, min: number, max: number) {
  return Math.max(min, Math.min(max, v));
}
function refLogNorm(value: number, min: number, max: number) {
  const lo = Math.log1p(Math.max(0, min));
  const hi = Math.log1p(Math.max(0, max));
  const v = Math.log1p(Math.max(0, value));
  const span = hi - lo;
  if (span <= 0) return 0;
  return refClamp((v - lo) / span, 0, 1);
}
function refRadius(value: number, min: number, max: number) {
  const t = refLogNorm(value, min, max);
  return refClamp(4 + t * 18, 3, 24);
}
function refColor(value: number, min: number, max: number) {
  const t = refLogNorm(value, min, max);
  const idx = Math.round(t * (ABUNDANCE_PALETTE.length - 1));
  return ABUNDANCE_PALETTE[refClamp(idx, 0, ABUNDANCE_PALETTE.length - 1)];
}

const SWEEP = [0, 1, 2, 3, 5, 8, 10, 25, 50, 100, 500, 1000, 5000];
const MIN = 1;
const MAX = 5000;

describe("abundance radius/colour snapshot (Phase 4 contract)", () => {
  it("nodeRadius(log1p) reproduces the original radiusForAbundance", () => {
    for (const v of SWEEP) {
      expect(nodeRadius(v, MIN, MAX, "log1p")).toBe(refRadius(v, MIN, MAX));
    }
  });

  it("colorForAbundance reproduces the original palette selection", () => {
    for (const v of SWEEP) {
      expect(colorForAbundance(v, MIN, MAX)).toBe(refColor(v, MIN, MAX));
    }
  });

  it("clamps at the palette and radius extremes", () => {
    expect(colorForAbundance(0, MIN, MAX)).toBe(ABUNDANCE_PALETTE[0]);
    expect(colorForAbundance(MAX, MIN, MAX)).toBe(ABUNDANCE_PALETTE[ABUNDANCE_PALETTE.length - 1]);
    expect(nodeRadius(MAX, MIN, MAX, "log1p")).toBe(22); // 4 + 1*18, within [3,24]
  });
});
