/**
 * Centralized, spec-driven file-type helpers. A method's `spec.json` declares
 * the MIME types it `accepts`; uploaded datasets carry an `original_filename`
 * and an optional `mime_type`. These utilities derive a coarse input format
 * and decide compatibility so the wizard can filter datasets, constrain the
 * upload field, and drive format-dependent field visibility — without any
 * per-method conditionals scattered in components.
 */

export type InputFormat = "fasta" | "csv" | "tsv" | "zip" | "rda" | "rds" | "unknown";

const EXT_TO_FORMAT: Record<string, InputFormat> = {
  fa: "fasta",
  fasta: "fasta",
  fna: "fasta",
  faa: "fasta",
  fas: "fasta",
  csv: "csv",
  tsv: "tsv",
  tab: "tsv",
  zip: "zip",
  rda: "rda",
  rdata: "rda",
  rds: "rds",
};

const MIME_TO_FORMAT: Record<string, InputFormat> = {
  "text/fasta": "fasta",
  "text/x-fasta": "fasta",
  "text/csv": "csv",
  "text/tab-separated-values": "tsv",
  "application/zip": "zip",
  "application/x-rda": "rda",
  "application/x-rds": "rds",
};

const FORMAT_TO_MIMES: Record<Exclude<InputFormat, "unknown">, string[]> = {
  fasta: ["text/fasta", "text/x-fasta"],
  csv: ["text/csv"],
  tsv: ["text/tab-separated-values"],
  zip: ["application/zip"],
  rda: ["application/x-rda"],
  rds: ["application/x-rds"],
};

const FORMAT_TO_EXTS: Record<Exclude<InputFormat, "unknown">, string[]> = {
  fasta: [".fasta", ".fa", ".fna", ".faa", ".fas"],
  csv: [".csv"],
  tsv: [".tsv", ".tab"],
  zip: [".zip"],
  rda: [".rda", ".rdata"],
  rds: [".rds"],
};

export function fileExtension(name: string | null | undefined): string {
  if (!name) return "";
  const idx = name.lastIndexOf(".");
  if (idx < 0 || idx === name.length - 1) return "";
  return name.slice(idx + 1).toLowerCase();
}

export function inputFormatFromName(name: string | null | undefined): InputFormat {
  return EXT_TO_FORMAT[fileExtension(name)] ?? "unknown";
}

export function inputFormatFromMime(mime: string | null | undefined): InputFormat {
  if (!mime) return "unknown";
  return MIME_TO_FORMAT[mime.toLowerCase()] ?? "unknown";
}

/** Extension-first (most reliable), MIME as fallback. */
export function inputFormatFromFile(file: {
  name?: string | null;
  mimeType?: string | null;
}): InputFormat {
  const byName = inputFormatFromName(file.name);
  if (byName !== "unknown") return byName;
  return inputFormatFromMime(file.mimeType);
}

/** The set of input formats a method accepts, derived from its MIME `accepts`. */
export function acceptsToFormats(accepts: string[] | undefined): Set<InputFormat> {
  const out = new Set<InputFormat>();
  for (const mime of accepts ?? []) {
    const fmt = inputFormatFromMime(mime);
    if (fmt !== "unknown") out.add(fmt);
  }
  return out;
}

/** True when an uploaded dataset is usable by a method (per its `accepts`). */
export function isFileCompatible(
  file: { original_filename: string; mime_type?: string | null },
  accepts: string[] | undefined,
): boolean {
  const allowed = accepts ?? [];
  if (file.mime_type && allowed.includes(file.mime_type)) return true;
  const formats = acceptsToFormats(allowed);
  const fileFormat = inputFormatFromFile({ name: file.original_filename, mimeType: file.mime_type });
  return fileFormat !== "unknown" && formats.has(fileFormat);
}

/** Builds a native `<input accept>` string (MIME types + extensions) for UX. */
export function acceptAttr(accepts: string[] | undefined): string {
  const tokens = new Set<string>(accepts ?? []);
  for (const fmt of acceptsToFormats(accepts)) {
    if (fmt === "unknown") continue;
    FORMAT_TO_EXTS[fmt].forEach((ext) => tokens.add(ext));
    FORMAT_TO_MIMES[fmt].forEach((mime) => tokens.add(mime));
  }
  return [...tokens].join(",");
}
