import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const methodDir = path.join(root, "methods", "brepphylo");

function loadJson(name: string) {
  return JSON.parse(readFileSync(path.join(methodDir, name), "utf8"));
}

describe("BrepPhylo param.schema.json", () => {
  const param = loadJson("param.schema.json");

  it("renames tree_type title to Tree inference method", () => {
    expect(param.properties.tree_type.title).toBe("Tree inference method");
  });

  it("defines species enum with custom default Homo_sapiens", () => {
    expect(param.properties.species.enum).toEqual([
      "Homo_sapiens",
      "Mus_musculus",
      "Bos_taurus",
      "Gallus_gallus",
      "Oryctolagus_cuniculus",
      "Sus_scrofa",
      "custom",
    ]);
    expect(param.properties.species.default).toBe("Homo_sapiens");
  });

  it("defines input_sequence_mode enum", () => {
    expect(param.properties.input_sequence_mode.enum).toEqual([
      "raw_sequence",
      "aligned_imgt_gapped",
    ]);
    expect(param.properties.input_sequence_mode.default).toBe("raw_sequence");
  });

  it("defines plot_type enum", () => {
    expect(param.properties.plot_type.enum).toEqual([
      "phylogram",
      "cladogram",
      "fan",
      "radial",
    ]);
  });

  it("includes germline_set_text and enable_csr_analysis", () => {
    expect(param.properties.germline_set_text).toBeDefined();
    expect(param.properties.enable_csr_analysis.default).toBe(true);
    expect(param.properties.isotype_column).toBeDefined();
  });

  it("removes deprecated parameters", () => {
    const removed = [
      "class_column",
      "germline_set",
      "use_temp_dir",
      "apply_filters",
      "uppercase",
      "gap_policy",
      "noniupac_policy",
      "max_class_categories",
    ];
    for (const key of removed) {
      expect(param.properties[key]).toBeUndefined();
    }
  });

  it("requires min_clone_size as positive integer", () => {
    expect(param.properties.min_clone_size.type).toBe("integer");
    expect(param.properties.min_clone_size.minimum).toBe(1);
    expect(param.required).toContain("min_clone_size");
  });
});

describe("BrepPhylo ui.json", () => {
  const ui = loadJson("ui.json");

  it("defines textarea widget for germline_set_text", () => {
    expect(ui.widgets?.germline_set_text).toBe("textarea");
  });

  it("defines conditional visibility rules", () => {
    expect(ui.visibility.collapse_and_replace).toEqual({ when: { tree_type: "dnapars" } });
    expect(ui.visibility.igphyml_accuracy).toEqual({ when: { tree_type: "igphyml" } });
    expect(ui.visibility.algorithm).toEqual({ when: { input_sequence_mode: "raw_sequence" } });
    expect(ui.visibility.germline_set_text).toEqual({ when: { species: "custom" } });
    expect(ui.visibility.isotype_column).toEqual({ when: { enable_csr_analysis: true } });
  });

  it("does not order removed fields", () => {
    const removed = [
      "class_column",
      "germline_set",
      "use_temp_dir",
      "apply_filters",
      "uppercase",
      "gap_policy",
      "noniupac_policy",
      "max_class_categories",
    ];
    for (const key of removed) {
      expect(ui.order).not.toContain(key);
    }
  });
});

describe("BrepPhylo result.schema.json", () => {
  const result = loadJson("result.schema.json");

  it("includes analysis and diagnostics blocks", () => {
    expect(result.properties.analysis).toBeDefined();
    expect(result.properties.diagnostics).toBeDefined();
    expect(result.properties.analysis.properties.batch_summary).toBeDefined();
    expect(result.properties.analysis.properties.csr_events).toBeDefined();
    expect(result.properties.analysis.properties.csr_summary_fallback).toBeDefined();
    expect(result.properties.diagnostics.properties.latex_available).toBeDefined();
  });

  it("does not expose clone_id_remap diagnostics", () => {
    expect(result.properties.diagnostics.properties.clone_id_remap).toBeUndefined();
  });

  it("records per-clone CSR status", () => {
    expect(result.properties.analysis.properties.per_clone_status.items.properties.status).toBeDefined();
  });

  it("nests artifact_zip_b64 under clone_bundle_zip", () => {
    expect(result.properties.artifact_zip_b64.properties.clone_bundle_zip).toBeDefined();
  });
});

describe("BrepPhylo UI visibility helper", () => {
  const ui = loadJson("ui.json");

  function testWhen(values: Record<string, unknown>, cond: Record<string, unknown>) {
    return Object.entries(cond).every(([k, expected]) => {
      const v = values[k];
      return Array.isArray(expected) ? expected.includes(v) : v === expected;
    });
  }

  function isVisible(field: string, values: Record<string, unknown>) {
    const rule = ui.visibility[field];
    if (!rule?.when) return true;
    return testWhen(values, rule.when);
  }

  it("shows collapse_and_replace only for dnapars", () => {
    expect(isVisible("collapse_and_replace", { tree_type: "dnapars" })).toBe(true);
    expect(isVisible("collapse_and_replace", { tree_type: "igphyml" })).toBe(false);
  });

  it("shows algorithm only for raw_sequence", () => {
    expect(isVisible("algorithm", { input_sequence_mode: "raw_sequence" })).toBe(true);
    expect(isVisible("algorithm", { input_sequence_mode: "aligned_imgt_gapped" })).toBe(false);
  });

  it("shows germline_set_text only for custom species", () => {
    expect(isVisible("germline_set_text", { species: "custom" })).toBe(true);
    expect(isVisible("germline_set_text", { species: "Homo_sapiens" })).toBe(false);
  });

  it("shows isotype_column only when CSR analysis enabled", () => {
    expect(isVisible("isotype_column", { enable_csr_analysis: true })).toBe(true);
    expect(isVisible("isotype_column", { enable_csr_analysis: false })).toBe(false);
  });
});
