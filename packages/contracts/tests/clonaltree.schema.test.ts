import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const methodDir = path.join(root, "methods", "clonaltree");

function loadJson(name: string) {
  return JSON.parse(readFileSync(path.join(methodDir, name), "utf8"));
}

function sectionFieldMap(ui: { sections?: Array<{ id: string; fields?: string[] }> }) {
  const fields = new Map<string, string[]>();

  for (const section of ui.sections ?? []) {
    for (const field of section.fields ?? []) {
      fields.set(field, [...(fields.get(field) ?? []), section.id]);
    }
  }

  return fields;
}

describe("ClonalTree ui.json", () => {
  const ui = loadJson("ui.json");

  it("defines full UI sections", () => {
    const ids = (ui.sections ?? []).map((section: { id: string }) => section.id);

    expect(ids).toEqual([
      "inputMapping",
      "runSelection",
      "cloneClustering",
      "refinement",
      "clonotypeGrouping",
      "treeConstruction",
    ]);
  });

  it("assigns every non-deprecated ordered field to exactly one section", () => {
    const sectionFields = sectionFieldMap(ui);

    for (const field of ui.order ?? []) {
      expect(sectionFields.get(field), `${field} should be sectioned`).toHaveLength(1);
    }

    expect(sectionFields.get("doMapping")).toEqual(["inputMapping"]);
    expect(sectionFields.get("run_name")).toEqual(["runSelection"]);
    expect(sectionFields.get("clone_cdr3_similarity")).toEqual(["cloneClustering"]);
    expect(sectionFields.get("use_refinement")).toEqual(["refinement"]);
    expect(sectionFields.get("clonotype_method")).toEqual(["clonotypeGrouping"]);
    expect(sectionFields.get("tree_revision")).toEqual(["treeConstruction"]);
  });

  it("keeps deprecated aliases out of UI order", () => {
    expect(ui.order).not.toContain("number_top_clone");
    expect(ui.order).not.toContain("initial_clustering_threshold");
  });

  it("preserves refinement mapping visibility rules", () => {
    for (const field of [
      "column_map.j_sequence_alignment",
      "column_map.v_sequence_alignment",
      "column_map.j_sequence_alignment_aa",
      "column_map.v_sequence_alignment_aa",
    ]) {
      expect(ui.visibility[field]).toEqual({ whenAll: [{ doMapping: true }, { use_refinement: true }] });
    }
  });

  it("keeps all mapping fields in the input mapping section", () => {
    const inputMapping = ui.sections.find((section: { id: string }) => section.id === "inputMapping");

    for (const field of (ui.order ?? []).filter((field: string) => field === "doMapping" || field.startsWith("column_map."))) {
      expect(inputMapping?.fields).toContain(field);
    }
  });
});
