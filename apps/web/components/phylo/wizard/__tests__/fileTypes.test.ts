import { describe, expect, it } from "vitest";
import { acceptAttr, inputFormatFromFile, isFileCompatible } from "@/lib/fileTypes";

const GCTREE_ACCEPTS = [
  "text/fasta",
  "text/x-fasta",
  "text/csv",
  "text/tab-separated-values",
  "application/zip",
];
const DOWSER_ACCEPTS = [
  "text/csv",
  "text/tab-separated-values",
  "application/x-rda",
  "application/x-rds",
];

describe("inputFormatFromFile", () => {
  it("derives format from extension first", () => {
    expect(inputFormatFromFile({ name: "reads.fasta" })).toBe("fasta");
    expect(inputFormatFromFile({ name: "table.tsv" })).toBe("tsv");
    expect(inputFormatFromFile({ name: "table.tab" })).toBe("tsv");
    expect(inputFormatFromFile({ name: "data.csv" })).toBe("csv");
  });

  it("falls back to MIME when the extension is unknown", () => {
    expect(inputFormatFromFile({ name: "blob", mimeType: "text/x-fasta" })).toBe("fasta");
    expect(inputFormatFromFile({ name: "blob" })).toBe("unknown");
  });
});

describe("isFileCompatible", () => {
  it("a FASTA uploaded for gctree is NOT compatible with dowser", () => {
    const fasta = { original_filename: "clone.fasta", mime_type: "text/fasta" };
    expect(isFileCompatible(fasta, GCTREE_ACCEPTS)).toBe(true);
    expect(isFileCompatible(fasta, DOWSER_ACCEPTS)).toBe(false);
  });

  it("a CSV is compatible with both", () => {
    const csv = { original_filename: "airr.csv", mime_type: "text/csv" };
    expect(isFileCompatible(csv, GCTREE_ACCEPTS)).toBe(true);
    expect(isFileCompatible(csv, DOWSER_ACCEPTS)).toBe(true);
  });

  it("matches by extension when mime_type is missing", () => {
    expect(isFileCompatible({ original_filename: "x.tsv" }, DOWSER_ACCEPTS)).toBe(true);
    expect(isFileCompatible({ original_filename: "x.zip" }, DOWSER_ACCEPTS)).toBe(false);
  });
});

describe("acceptAttr", () => {
  it("includes both extensions and MIME types for the input element", () => {
    const attr = acceptAttr(DOWSER_ACCEPTS);
    expect(attr).toContain(".csv");
    expect(attr).toContain(".rds");
    expect(attr).toContain("text/csv");
    expect(attr).not.toContain(".fasta");
  });
});
