import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "../../../../..");
const uiPath = path.join(repoRoot, "packages/contracts/methods/brepphylo/ui.json");
const paramPath = path.join(repoRoot, "packages/contracts/methods/brepphylo/param.schema.json");

type VisibilityRule = { when?: Record<string, unknown> };
type UiHints = {
  visibility?: Record<string, VisibilityRule>;
  widgets?: Record<string, string>;
};

function testWhen(values: Record<string, unknown>, cond: Record<string, unknown>) {
  return Object.entries(cond).every(([k, expected]) => {
    const v = values[k];
    return Array.isArray(expected) ? expected.includes(v) : v === expected;
  });
}

function isFieldVisible(visibility: Record<string, VisibilityRule>, name: string, values: Record<string, unknown>) {
  const vis = visibility[name];
  if (!vis?.when) return true;
  return testWhen(values, vis.when);
}

describe("FormBuilder BrepPhylo conditional fields", () => {
  const ui = JSON.parse(readFileSync(uiPath, "utf8")) as UiHints;
  const param = JSON.parse(readFileSync(paramPath, "utf8")) as {
    properties: Record<string, { title?: string }>;
  };
  const visibility = ui.visibility ?? {};

  it("uses Tree inference method label in param schema", () => {
    expect(param.properties.tree_type.title).toBe("Tree inference method");
  });

  it("registers textarea widget for germline_set_text", () => {
    expect(ui.widgets?.germline_set_text).toBe("textarea");
  });

  it("gates collapse_and_replace on dnapars", () => {
    expect(isFieldVisible(visibility, "collapse_and_replace", { tree_type: "dnapars" })).toBe(true);
    expect(isFieldVisible(visibility, "collapse_and_replace", { tree_type: "simple" })).toBe(false);
  });

  it("gates igphyml_accuracy on igphyml", () => {
    expect(isFieldVisible(visibility, "igphyml_accuracy", { tree_type: "igphyml" })).toBe(true);
    expect(isFieldVisible(visibility, "igphyml_accuracy", { tree_type: "dnapars" })).toBe(false);
  });

  it("gates algorithm on raw_sequence mode", () => {
    expect(isFieldVisible(visibility, "algorithm", { input_sequence_mode: "raw_sequence" })).toBe(true);
    expect(isFieldVisible(visibility, "algorithm", { input_sequence_mode: "aligned_imgt_gapped" })).toBe(false);
  });

  it("gates germline_set_text on custom species", () => {
    expect(isFieldVisible(visibility, "germline_set_text", { species: "custom" })).toBe(true);
    expect(isFieldVisible(visibility, "germline_set_text", { species: "Homo_sapiens" })).toBe(false);
  });

  it("gates isotype_column on enable_csr_analysis", () => {
    expect(isFieldVisible(visibility, "isotype_column", { enable_csr_analysis: true })).toBe(true);
    expect(isFieldVisible(visibility, "isotype_column", { enable_csr_analysis: false })).toBe(false);
  });
});
