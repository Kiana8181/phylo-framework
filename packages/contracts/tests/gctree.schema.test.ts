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
    const expectedMappingRule = {
      whenAll: [{ doMapping: true }, { $inputFormat: ["csv", "tsv"] }],
    };

    expect(ui.visibility["column_map.sequence_id"]).toEqual(expectedMappingRule);
    expect(ui.visibility["column_map.sequence_alignment"]).toEqual(expectedMappingRule);
  });

  it("preserves scenario-based run option visibility rules", () => {
    const expectedScenarioRule = {
      whenAny: [
        { input_scenario: "aligned_fasta_with_root" },
        { input_scenario: "airr_or_changeo_table_adapter" },
      ],
    };

    expect(ui.visibility.quick).toEqual(expectedScenarioRule);
    expect(ui.visibility.jumble).toEqual(expectedScenarioRule);
  });

  it("preserves coloring mode visibility", () => {
    expect(ui.visibility.color_mode).toEqual({ when: { apply_coloring_settings: true } });
  });

  // The germline question and the two fields it reveals only work if the
  // visibility rules stay mutually exclusive: `root` names a row that exists,
  // the other two describe a row to create, and showing both at once would ask
  // the user to root on two different things.
  describe("germline row question", () => {
    const addingRootRow = {
      input_scenario: "airr_or_changeo_table_adapter",
      germline_row_present: "no",
    };

    it("asks the question only for the tabular adapter scenario", () => {
      expect(ui.visibility.germline_row_present).toEqual({
        when: { input_scenario: "airr_or_changeo_table_adapter" },
      });
    });

    it("keeps Root sequence ID for FASTA input and for tables that carry the row", () => {
      expect(ui.visibility.root).toEqual({
        whenAny: [
          { input_scenario: "aligned_fasta_with_root" },
          {
            input_scenario: "airr_or_changeo_table_adapter",
            germline_row_present: "yes",
          },
        ],
      });
    });

    it("reveals the root ID and sequence fields only when the row must be added", () => {
      expect(ui.visibility.root_sequence_id).toEqual({ when: addingRootRow });
      expect(ui.visibility.root_sequence_alignment).toEqual({ when: addingRootRow });
    });

    it("requires both new fields exactly when they are visible", () => {
      const required = new Map(
        (ui.validation?.requiredWhen ?? []).map(
          (rule: { field: string; when: unknown }) => [rule.field, rule.when],
        ),
      );

      expect(required.get("root_sequence_id")).toEqual(addingRootRow);
      expect(required.get("root_sequence_alignment")).toEqual(addingRootRow);
    });
  });
});

describe("GCtree param.schema.json", () => {
  const params = loadJson("param.schema.json");
  const ui = loadJson("ui.json");

  it("defaults the germline question to 'yes' so existing behaviour is unchanged", () => {
    expect(params.properties.germline_row_present.enum).toEqual(["yes", "no"]);
    expect(params.properties.germline_row_present.default).toBe("yes");
  });

  it("declares the fields the germline visibility rules reference", () => {
    for (const field of ["germline_row_present", "root_sequence_id", "root_sequence_alignment"]) {
      expect(params.properties[field], `${field} should be declared`).toBeDefined();
    }
  });

  it("renders the pasted germline sequence in a textarea", () => {
    expect(ui.widgets?.root_sequence_alignment).toBe("textarea");
  });
});
