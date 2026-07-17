import { clamp, logNorm } from "./math";
import type { ColorScale } from "./types";

// Viridis-like 10-stop ramp, ported verbatim from LineageSVG. Phase 4 will add
// categorical + continuous colour-by-field on top; Phase 1 only ports the
// abundance ramp so the default lineage colouring is byte-identical.
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

/** Build the abundance ColorScale over an extent. */
export function buildAbundanceScale(min: number, max: number): ColorScale {
  return {
    kind: "abundance",
    domainMin: min,
    domainMax: max,
    colorFor: (value: number) => colorForAbundance(value, min, max),
  };
}
