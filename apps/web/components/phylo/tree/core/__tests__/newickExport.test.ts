import { describe, it, expect } from "vitest";
import { newickExportEntries } from "../download";

const INTERNAL = "(seq1:1,seq2:1)naive:0;";
const DISPLAY = "(orig1:1,'a:b':1)naive:0;";

describe("newickExportEntries", () => {
  it("offers both entries with original IDs first (default) when displayNewick is present", () => {
    const entries = newickExportEntries({
      filename: "tree-1",
      internalNewick: INTERNAL,
      displayNewick: DISPLAY,
    });
    expect(entries.map((e) => e.label)).toEqual([
      "Newick (original IDs)",
      "Newick (internal labels)",
    ]);
    // Original-IDs entry serializes the display newick to <name>.nwk.
    expect(entries[0]).toMatchObject({ filename: "tree-1.nwk", newick: DISPLAY, disabled: false });
    // Internal entry keeps the canonical newick under a distinct filename.
    expect(entries[1]).toMatchObject({
      filename: "tree-1.internal.nwk",
      newick: INTERNAL,
      disabled: false,
    });
  });

  it("shows only the internal-labels entry when displayNewick is absent", () => {
    const entries = newickExportEntries({ filename: "tree-1", internalNewick: INTERNAL });
    expect(entries.map((e) => e.label)).toEqual(["Newick (internal labels)"]);
    expect(entries[0].filename).toBe("tree-1.internal.nwk");
  });

  it("treats an empty/whitespace displayNewick as absent (fallback)", () => {
    for (const displayNewick of [null, undefined, "", "   "]) {
      const entries = newickExportEntries({ filename: "t", internalNewick: INTERNAL, displayNewick });
      expect(entries.map((e) => e.label)).toEqual(["Newick (internal labels)"]);
    }
  });

  it("disables the internal entry when the canonical newick is empty", () => {
    const entries = newickExportEntries({
      filename: "t",
      internalNewick: "   ",
      displayNewick: DISPLAY,
    });
    // Display entry still enabled; internal entry disabled but present.
    expect(entries[0].disabled).toBe(false);
    expect(entries[1].disabled).toBe(true);
  });
});
