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
});

describe("Dowser results presentation contracts", () => {
  it("includes canonical_ids in stats for label warning visibility", () => {
    const stats = { canonical_ids: "sequence_id", label_field: "sample_id" };
    expect(stats.canonical_ids).toBe("sequence_id");
  });

  it("artifact list supports download links when present", () => {
    const artifacts = [
      { name: "all_sequences.fasta", path: "all_sequences.fasta", kind: "fasta" },
      { name: "input_qc.json", path: "input_qc.json", kind: "json" },
    ];
    expect(artifacts.every((a) => a.name && a.kind)).toBe(true);
  });
});
