import type { PhyloAnnotation } from "./types";
import type { DetailRow } from "./lineageDisplay";

/**
 * Annotation lookup + title/rows helpers for the phylogeny view, ported verbatim
 * from TreeSVG. Rebased onto `PhyloAnnotation` (was an inline `any`-typed Anno).
 */

export function buildAnnoLookup(annotations?: readonly PhyloAnnotation[]): Record<string, PhyloAnnotation> {
  const m: Record<string, PhyloAnnotation> = {};
  (annotations ?? []).forEach((a) => {
    if (!a) return;
    const keys = [a.final_tip_label, a.sequence_id, a.label].filter(
      (k): k is string => typeof k === "string" && k.trim().length > 0,
    );
    for (const key of keys) {
      m[key.trim()] = a;
    }
  });
  return m;
}

export function resolveAnno(
  lookup: Record<string, PhyloAnnotation>,
  tipName: string,
): PhyloAnnotation | undefined {
  return lookup[tipName];
}

// The render path passes a node's `attrs` (a looser attribute bag) here, so the
// anno param is typed as a plain string-keyed record rather than PhyloAnnotation.
type AttrBag = Record<string, unknown>;

export function buildTipTitle(
  label: string,
  anno: AttrBag | undefined,
  colorField: string | null,
  displayField: string | null,
): string {
  if (typeof anno?.tooltip === "string" && anno.tooltip.trim()) {
    return anno.tooltip.trim();
  }

  const lines: string[] = [];
  const displayValue = (displayField && String(anno?.[displayField] ?? "").trim()) || label;
  if (displayValue) lines.push(displayValue);

  if (!anno) return lines.join("\n");

  const seqId = String(anno.sequence_id ?? "").trim();
  if (seqId && seqId !== displayValue) lines.push(`sequence_id: ${seqId}`);

  if (colorField) {
    const cval = String(anno[colorField] ?? "").trim();
    if (cval) lines.push(`${colorField}: ${cval}`);
  }

  const skip = new Set<string>(["label", "sequence_id", "tooltip"]);
  if (displayField) skip.add(displayField);
  if (colorField) skip.add(colorField);

  const extras = Object.keys(anno)
    .filter((k) => !skip.has(k))
    .sort((a, b) => a.localeCompare(b, "en"));

  for (const k of extras) {
    const v = String(anno[k] ?? "").trim();
    if (v) lines.push(`${k}: ${v}`);
  }

  return lines.join("\n");
}

/** Structured field rows for the node-detail modal (clicking a tip). */
export function buildTipRows(
  label: string,
  anno: AttrBag | undefined,
  displayField: string | null,
): { title: string; rows: DetailRow[] } {
  const title = (displayField && String(anno?.[displayField] ?? "").trim()) || label;
  const rows: DetailRow[] = [{ key: "label", value: label }];
  if (anno) {
    const seq = String(anno.sequence_id ?? "").trim();
    if (seq) rows.push({ key: "sequence_id", value: seq });
    const skip = new Set<string>(["label", "sequence_id", "tooltip"]);
    for (const k of Object.keys(anno)
      .filter((k) => !skip.has(k))
      .sort((a, b) => a.localeCompare(b, "en"))) {
      const v = String(anno[k] ?? "").trim();
      if (v) rows.push({ key: k, value: v });
    }
  }
  return { title, rows };
}

export function resolveTipDisplayLabel(
  label: string,
  anno: AttrBag | undefined,
  displayField: string | null | undefined,
): string {
  return (displayField && String(anno?.[displayField] ?? "").trim()) || label;
}
