import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const methodDir = path.join(root, "methods", "dowser");

function loadJson(name: string) {
  return JSON.parse(readFileSync(path.join(methodDir, name), "utf8"));
}

describe("Dowser param.schema.json", () => {
  const param = loadJson("param.schema.json");

  it("defines full tree_build enum", () => {
    expect(param.properties.tree_build.enum).toEqual([
      "pratchet",
      "pml",
      "dnapars",
      "dnaml",
      "igphyml",
      "raxml",
    ]);
  });

  it("defines analysis_mode enum", () => {
    expect(param.properties.analysis_mode.enum).toEqual([
      "tree_only",
      "tree_with_internal_sequences",
      "discrete_trait_analysis",
      "time_evolution",
    ]);
  });

  it("removes destructive filter parameters", () => {
    const removed = [
      "apply_filters",
      "uppercase",
      "gap_policy",
      "noniupac_policy",
      "len_policy",
      "ig_stop_policy",
    ];
    for (const key of removed) {
      expect(param.properties[key]).toBeUndefined();
    }
  });

  it("includes DTA and IgPhyML params", () => {
    expect(param.properties.trait_field).toBeDefined();
    expect(param.properties.trait_model.enum).toContain("isotype_irreversible");
    expect(param.properties.partition_model.enum).toContain("cf");
    expect(param.properties.chain_mode.enum).toEqual(["H", "HL"]);
  });

  it("includes explicit formatClones safety flags", () => {
    expect(param.properties.mod3.default).toBe(false);
    expect(param.properties.filterstop.default).toBe(false);
    expect(param.properties.use_regions.default).toBe(false);
  });

  it("requires tree_build", () => {
    expect(param.required).toContain("tree_build");
  });

  it("uses column_map only for column renaming (no R-side *_column params)", () => {
    const removed = [
      "sequence_column",
      "germline_column",
      "clone_column",
      "id_column",
      "v_call_column",
      "j_call_column",
      "junction_length_column",
      "junction_column",
      "cell_id_column",
      "locus_column",
    ];
    for (const key of removed) {
      expect(param.properties[key]).toBeUndefined();
    }
    expect(param.properties.column_map.properties.cell_id).toBeDefined();
    expect(param.properties.column_map.properties.locus).toBeDefined();
  });
});

describe("Dowser result.schema.json", () => {
  const result = loadJson("result.schema.json");

  it("allows trees_detail and DTA payloads", () => {
    expect(result.properties.trees_detail).toBeDefined();
    expect(result.properties.discrete_trait_analysis).toBeDefined();
    expect(result.properties.time_evolution).toBeDefined();
    expect(result.properties.input_qc).toBeDefined();
    expect(result.properties.data_provenance).toBeDefined();
    expect(result.properties.artifacts).toBeDefined();
    expect(result.properties.artifact_zip_b64).toBeDefined();
    expect(result.properties.artifact_name).toBeDefined();
    expect(result.properties.discrete_trait_analysis.additionalProperties).toBe(true);
    expect(result.properties.input_qc.additionalProperties).toBe(true);
    expect(result.properties.igphyml.additionalProperties).toBe(true);
  });
});

describe("Dowser ui.json", () => {
  const ui = loadJson("ui.json");

  it("does not expose removed filter fields in order", () => {
    const removed = ["apply_filters", "uppercase", "gap_policy", "noniupac_policy", "len_policy"];
    for (const key of removed) {
      expect(ui.order).not.toContain(key);
    }
  });

  it("includes new UI sections", () => {
    const ids = (ui.sections ?? []).map((s: { id: string }) => s.id);
    expect(ids).toContain("treeConstruction");
    expect(ids).toContain("internalSequences");
    expect(ids).toContain("dta");
    expect(ids).toContain("igphyml");
    expect(ids).toContain("pairedChain");
    expect(ids).toContain("timeEvolution");
  });

  it("gates DTA fields on analysis_mode", () => {
    expect(ui.visibility.trait_field.when.analysis_mode).toBe("discrete_trait_analysis");
    expect(ui.visibility.partition_model.when.tree_build).toBe("igphyml");
  });
});
