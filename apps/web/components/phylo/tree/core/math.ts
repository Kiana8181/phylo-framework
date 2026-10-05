// Numeric helpers ported verbatim from LineageSVG. Do not change behaviour:
// the Phase 4 colour work asserts these against snapshots taken before the port.

export function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function isFiniteNumber(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value);
}

export function toAbundance(value: unknown): number | undefined {
  if (value == null || value === "") return undefined;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n) || n < 0) return undefined;
  return n;
}

/** Log-normalise `value` into [0,1] over [min,max]. */
export function logNorm(value: number, min: number, max: number): number {
  const lo = Math.log1p(Math.max(0, min));
  const hi = Math.log1p(Math.max(0, max));
  const v = Math.log1p(Math.max(0, value));
  const span = hi - lo;
  if (span <= 0) return 0;
  return clamp((v - lo) / span, 0, 1);
}

/** Linear-normalise `value` into [0,1] over [min,max]. */
export function linNorm(value: number, min: number, max: number): number {
  const span = max - min;
  if (span <= 0) return 0;
  return clamp((value - min) / span, 0, 1);
}
