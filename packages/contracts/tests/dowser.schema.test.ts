import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const methodDir = path.join(root, "methods", "dowser");

function loadJson(name: string) {
  return JSON.parse(readFileSync(path.join(methodDir, name), "utf8"));
}

function leafPropertyNames(properties: Record<string, any>, prefix = ""): string[] {
  return Object.entries(properties).flatMap(([key, value]) => {
    const pathName = prefix ? `${prefix}.${key}` : key;
    return value?.properties ? leafPropertyNames(value.properties, pathName) : [pathName];
  });
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
    expect(param.properties.trait_fields.description).toContain("formatClones");
    expect(param.properties.trait_model.enum).toContain("isotype_irreversible");
    expect(param.properties.modelfile.title).toBe("Custom trait model file");
    expect(param.properties.partition_model.enum).toEqual(["single", "cf", "hl", "hlf", "hlc", "hlcf"]);
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

  it("does not expose deprecated tree_model alias", () => {
    expect(param.properties.tree_model).toBeUndefined();
  });

  it("does not expose server-managed IgPhyML path settings", () => {
    expect(param.properties.igphyml_exec).toBeUndefined();
    expect(param.properties.igphyml_motifs).toBeUndefined();
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
    expect(param.properties.column_map.properties.v_region_start).toBeDefined();
    expect(param.properties.column_map.properties.v_region_end).toBeDefined();
    expect(param.properties.column_map.properties.j_region_start).toBeDefined();
    expect(param.properties.column_map.properties.j_region_end).toBeDefined();
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
  const param = loadJson("param.schema.json");

  it("does not expose removed filter fields in order", () => {
    const removed = ["apply_filters", "uppercase", "gap_policy", "noniupac_policy", "len_policy"];
    for (const key of removed) {
      expect(ui.order).not.toContain(key);
    }
  });

  it("includes new UI sections", () => {
    const ids = (ui.sections ?? []).map((s: { id: string }) => s.id);
    expect(ids).toContain("treeConstruction");
    expect(ids).toContain("outputPlotting");
    expect(ids).toContain("internalSequences");
    expect(ids).toContain("dta");
    expect(ids).toContain("igphyml");
    expect(ids).toContain("pairedChain");
    expect(ids).toContain("timeEvolution");
  });

  it("gates DTA fields on analysis_mode", () => {
    expect(ui.visibility.trait_field.when.analysis_mode).toBe("discrete_trait_analysis");
    expect(ui.visibility.modelfile.when.analysis_mode).toBe("discrete_trait_analysis");
    expect(ui.visibility.partition_model.when.tree_build).toBe("igphyml");
  });

  it("keeps internal sequence output available except in time evolution mode", () => {
    expect(ui.visibility.return_internal_sequences.whenAny).toEqual([
      { analysis_mode: "tree_with_internal_sequences" },
      { analysis_mode: "tree_only" },
      { analysis_mode: "discrete_trait_analysis" },
    ]);
  });

  it("shows paired-chain fields only for HL mode", () => {
    expect(ui.sections.find((s: { id: string }) => s.id === "inputMapping")?.fields).toContain("column_map.cell_id");
    expect(ui.sections.find((s: { id: string }) => s.id === "inputMapping")?.fields).toContain("column_map.locus");
    expect(ui.visibility["column_map.cell_id"].whenAll).toEqual([{ doMapping: true }, { chain_mode: "HL" }]);
    expect(ui.visibility["column_map.locus"].whenAll).toEqual([{ doMapping: true }, { chain_mode: "HL" }]);
    expect(ui.visibility.heavy_locus.when.chain_mode).toBe("HL");
    expect(ui.visibility.split_light.when.chain_mode).toBe("HL");
    expect(ui.visibility.light_traits.when.chain_mode).toBe("HL");
    expect(ui.visibility.majoronly.when.chain_mode).toBe("HL");
  });

  it("shows region mapping fields only when use_regions mapping is enabled", () => {
    const inputMapping = ui.sections.find((s: { id: string }) => s.id === "inputMapping");
    for (const field of [
      "column_map.v_region_start",
      "column_map.v_region_end",
      "column_map.j_region_start",
      "column_map.j_region_end",
    ]) {
      expect(inputMapping?.fields).toContain(field);
      expect(ui.visibility[field].whenAll).toEqual([{ doMapping: true }, { use_regions: true }]);
    }
  });

  it("renders custom trait model file as a textarea in DTA", () => {
    expect(ui.widgets?.modelfile).toBe("textarea");
    const dta = (ui.sections ?? []).find((s: { id: string }) => s.id === "dta");
    const treeConstruction = (ui.sections ?? []).find((s: { id: string }) => s.id === "treeConstruction");
    expect(dta?.fields).toContain("modelfile");
    expect(dta?.fields).not.toContain("trait_fields");
    expect(treeConstruction?.fields).toContain("trait_fields");
    expect(dta?.fields).toContain("permute_all");
    expect(dta?.fields).toContain("alternative");
  });

  it("assigns every ordered field to exactly one section", () => {
    const sectionFields = new Map<string, string[]>();

    for (const section of ui.sections ?? []) {
      for (const field of section.fields ?? []) {
        sectionFields.set(field, [...(sectionFields.get(field) ?? []), section.id]);
      }
    }

    for (const field of ui.order ?? []) {
      expect(sectionFields.get(field), `${field} should be sectioned`).toHaveLength(1);
    }

    expect(sectionFields.get("unknown_value")).toEqual(["outputPlotting"]);
    expect(sectionFields.get("numeric_annotation_fields")).toEqual(["outputPlotting"]);
    expect(sectionFields.get("columns")).toEqual(["outputPlotting"]);
    expect(sectionFields.get("max_tip_categories")).toEqual(["outputPlotting"]);
  });

  it("intentionally orders and sections every schema field", () => {
    const fields = leafPropertyNames(param.properties);
    const ordered = new Set(ui.order ?? []);
    const sectioned = new Set((ui.sections ?? []).flatMap((section: { fields?: string[] }) => section.fields ?? []));

    for (const field of fields) {
      expect(ordered.has(field), `${field} should be in ui.order`).toBe(true);
      expect(sectioned.has(field), `${field} should be in a UI section`).toBe(true);
    }
  });
});
