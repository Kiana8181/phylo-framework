/**
 * Detects GCtree's `name@abundance` FASTA header convention.
 *
 * GCtree writes IDs like `seq3@9` in its own output but cannot read them back —
 * its `deduplicate` step only treats all-digit IDs as counts — so the abundances
 * are silently lost, and the `@` additionally breaks the DNAPARS root lookup.
 * The GCtree form therefore asks what the number means, and this decides when to
 * show that question.
 *
 * NOTE: the regex is intentionally duplicated in `services/gctree/app.py`
 * (FASTA_ID_AT_ABUNDANCE_RE) and `apps/api/services/fasta_id_style.py` — three
 * deploy units with no shared runtime. Keep all three in sync.
 */

export type FastaIdStyle = "at_abundance" | "other_at" | "plain" | "unknown";

const AT_ABUNDANCE_RE = /^[^@\s]+@\d+$/;

/** Enough of a file to see every header in any realistic clonal-family FASTA. */
export const FASTA_PEEK_BYTES = 256 * 1024;

/**
 * Classify the `>` headers of a (possibly partial) FASTA. When `truncated`, the
 * final line is dropped — it may be a header cut in half.
 */
export function classifyFastaHeaders(text: string, truncated = false): FastaIdStyle {
  let lines = text.split(/\r?\n/);
  if (truncated && lines.length > 0) lines = lines.slice(0, -1);

  let hasAt = false;
  let allAtAbundance = true;
  let sawAny = false;

  for (const line of lines) {
    if (!line.startsWith(">")) continue;
    const id = line.slice(1).trim().split(/\s+/)[0] ?? "";
    if (!id) continue;
    sawAny = true;
    if (id.includes("@")) hasAt = true;
    if (!AT_ABUNDANCE_RE.test(id)) allAtAbundance = false;
  }

  if (!sawAny || !hasAt) return "plain";
  return allAtAbundance ? "at_abundance" : "other_at";
}

/** Read only the first chunk of a picked file and classify its headers. */
export async function classifyFastaFile(file: File): Promise<FastaIdStyle> {
  try {
    const truncated = file.size > FASTA_PEEK_BYTES;
    const text = await file.slice(0, FASTA_PEEK_BYTES).text();
    return classifyFastaHeaders(text, truncated);
  } catch {
    return "unknown";
  }
}
