import { clamp, logNorm, linNorm } from "./math";
import { MIN_RADIUS, MAX_RADIUS } from "./constants";

export type RadiusScaleType = "log1p" | "linear";

/**
 * Unified node radius for both views. Signed-off decision (spec §1.4): default
 * to log1p for lineage AND phylogeny — BCR abundance is heavy-tailed, so a
 * linear scale renders every node but the dominant clone at the floor.
 *
 * `log1p` reproduces LineageSVG's original `radiusForAbundance` exactly:
 *   clamp(4 + logNorm(value,min,max) * 18, MIN_RADIUS, MAX_RADIUS).
 * `linear` is retained behind the same function (not a second copy) so a caller
 * can opt back into min–max scaling if ever needed.
 */
export function nodeRadius(
  value: number | undefined,
  min: number,
  max: number,
  scaleType: RadiusScaleType = "log1p",
): number {
  if (value === undefined || value <= 0) return MIN_RADIUS;
  const t = scaleType === "linear" ? linNorm(value, min, max) : logNorm(value, min, max);
  return clamp(4 + t * 18, MIN_RADIUS, MAX_RADIUS);
}
