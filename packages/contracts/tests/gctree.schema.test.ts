import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const methodDir = path.join(root, "methods", "gctree");

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

describe("GCtree ui.json", () => {
  const ui = loadJson("ui.json");

  it("defines full UI sections", () => {
    const ids = (ui.sections ?? []).map((section: { id: string }) => section.id);

    expect(ids).toEqual(["inputMapping", "inferenceRanking", "outputRendering", "advanced"]);
  });

  it("assigns every ordered field to exactly one section", () => {
    const sectionFields = sectionFieldMap(ui);

    for (const field of ui.order ?? []) {
      expect(sectionFields.get(field), `${field} should be sectioned`).toHaveLength(1);
    }

    expect(sectionFields.get("input_scenario")).toEqual(["inputMapping"]);
    expect(sectionFields.get("root")).toEqual(["inputMapping"]);
    expect(sectionFields.get("top_n")).toEqual(["inferenceRanking"]);
    expect(sectionFields.get("color_mode")).toEqual(["outputRendering"]);
    expect(sectionFields.get("apply_isotype")).toEqual(["advanced"]);
  });

  it("preserves input mapping visibility rules", () => {
    expect(ui.visibility["column_map.sequence_id"]).toEqual({ when: { doMapping: true } });
    expect(ui.visibility["column_map.sequence_alignment"]).toEqual({ when: { doMapping: true } });
  });

  it("preserves scenario-based run option visibility rules", () => {
    const expectedScenarioRule = {
      whenAny: [
        { input_scenario: "aligned_fasta_with_root" },
        { input_scenario: "airr_or_changeo_table_adapter" },
      ],
    };

    expect(ui.visibility.root).toEqual(expectedScenarioRule);
    expect(ui.visibility.quick).toEqual(expectedScenarioRule);
    expect(ui.visibility.jumble).toEqual(expectedScenarioRule);
  });

  it("preserves coloring mode visibility", () => {
    expect(ui.visibility.color_mode).toEqual({ when: { apply_coloring_settings: true } });
  });
});
