// Text/label helpers shared by both renderers. Ported verbatim from
// LineageSVG (truncateLabel, splitByHighlight) and TreeSVG (estimateTextWidth).

export function truncateLabel(label: string, maxChars: number): string {
  if (maxChars <= 1) return "…";
  if (label.length <= maxChars) return label;
  return `${label.slice(0, maxChars - 1).trimEnd()}…`;
}

export function estimateTextWidth(label: string, fontSize: number): number {
  return Math.ceil(fontSize * 0.6 * (label?.length ?? 0));
}

/** Split `text` into highlighted/non-highlighted runs by case-insensitive
 * substring match of `highlight`. Used for the search highlight in labels. */
export function splitByHighlight(
  text: string,
  highlight: string,
): Array<{ text: string; highlight: boolean }> {
  if (!highlight || !highlight.trim()) return [{ text, highlight: false }];
  const needle = highlight.trim();
  const lower = text.toLowerCase();
  const needleLower = needle.toLowerCase();
  const parts: Array<{ text: string; highlight: boolean }> = [];
  let start = 0;
  while (true) {
    const i = lower.indexOf(needleLower, start);
    if (i === -1) {
      if (start < text.length) parts.push({ text: text.slice(start), highlight: false });
      break;
    }
    if (i > start) parts.push({ text: text.slice(start, i), highlight: false });
    parts.push({ text: text.slice(i, i + needle.length), highlight: true });
    start = i + needle.length;
  }
  return parts.length ? parts : [{ text, highlight: false }];
}
