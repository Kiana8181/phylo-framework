import { describe, expect, it } from "vitest";
import { readDowserResult } from "@phylo/contracts";

describe("readDowserResult", () => {
  it("detects Dowser payloads and exposes artifacts", () => {
    const result = readDowserResult({
      ok: true,
      trees: ["((s1,s2),Germline);"],
      clones: { clone_id: ["c1"], seqs: [2] },
      annotations: [[]],
      stats: { analysis_mode: "tree_with_internal_sequences", tree_build: "pratchet", canonical_ids: "sequence_id" },
      trees_detail: [
        {
          clone_id: "c1",
          canonical_newick: "((s1,s2),Germline);",
          nodes: [{ node_id: "N1", is_internal: true, sequence: "ACGT" }],
        },
      ],
      artifacts: [{ name: "canonical_newick.nwk", kind: "newick" }],
      discrete_trait_analysis: {
        interpretation_warning: "caveat",
        switches: [{ from: "IGHM", to: "IGHG1" }],
      },
    });

    expect(result.isDowser).toBe(true);
    expect(result.treesDetail).toHaveLength(1);
    expect(result.artifacts).toHaveLength(1);
    expect(result.dta?.switches).toHaveLength(1);
  });

  it("returns empty for non-Dowser results", () => {
    const result = readDowserResult({
      ok: true,
      trees: [],
      clones: null,
      annotations: [],
      stats: { n_clones: 0 },
    });
    expect(result.isDowser).toBe(false);
    expect(result.artifacts).toEqual([]);
  });

  it("normalizes R-shaped input_qc fields for UI display", () => {
    const result = readDowserResult({
      ok: true,
      trees: ["((s1,s2),Germline);"],
      clones: { clone_id: ["c1"], seqs: [2] },
      annotations: [[]],
      stats: { analysis_mode: "tree_only", tree_build: "pratchet" },
      input_qc: {
        n_rows_original: 120,
        n_rows_after_trait_exclusion: 118,
        n_clones_original: 12,
        n_clones_after_trait_exclusion: 11,
        excluded_missing_trait: [{ sequence_id: "s1" }],
        length_mismatch: [],
        duplicate_sequence_ids: [],
      },
      chain_qc: { chain_mode: "H" },
    });

    expect(result.inputQc?.n_input_rows).toBe(120);
    expect(result.inputQc?.n_working_rows).toBe(118);
    expect(result.inputQc?.n_clones_input).toBe(12);
    expect(result.inputQc?.n_clones_working).toBe(11);
    expect(result.inputQc?.n_excluded_trait_missing).toBe(1);
  });
});
