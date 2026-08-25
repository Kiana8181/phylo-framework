/**
 * Wires the real GCtree contracts JSON to the form logic that consumes it.
 *
 * The germline question decides which of two mutually exclusive things the user
 * is telling us: `root` *names* a row already in their table, while
 * `root_sequence_id` / `root_sequence_alignment` *describe a row to create*.
 * Three files have to agree for that to hold — the param schema declares the
 * fields, ui.json gates them on `germline_row_present`, and the same condition
 * makes the two new ones required. Get one wrong and the form either asks for a
 * root twice or not at all, and the run dies in the service with "Root sequence
 * ID 'GL' not found among FASTA headers".
 */
import { describe, expect, it } from "vitest";
import { buildZodSchema, matchesRule } from "@/components/ui/FormBuilder";
import paramSchema from "@phylo/contracts/methods/gctree/param.schema.json";
import uiHints from "@phylo/contracts/methods/gctree/ui.json";

const schema = { ...(paramSchema as any), uiHints } as any;

const visibilityFor = (name: string) =>
  (uiHints as any).visibility?.[name];

const ADAPTER = "airr_or_changeo_table_adapter";
const FASTA = "aligned_fasta_with_root";

describe("gctree germline row contract wiring", () => {
  it("defaults the question to 'yes' so the Root sequence ID field keeps showing", () => {
    const def = (paramSchema as any).properties.germline_row_present;
    expect(def).toBeDefined();
    expect(def.enum).toEqual(["yes", "no"]);
    expect(def.default).toBe("yes");
  });

  it("lists all three fields in the order and the Input & Mapping section", () => {
    const ui = uiHints as any;
    const section = ui.sections.find((s: { id: string }) => s.id === "inputMapping");

    for (const field of [
      "germline_row_present",
      "root_sequence_id",
      "root_sequence_alignment",
    ]) {
      expect(ui.order, `${field} in order`).toContain(field);
      expect(section.fields, `${field} in inputMapping`).toContain(field);
    }
  });

  it("asks the question only for the tabular adapter scenario", () => {
    const rule = visibilityFor("germline_row_present");
    expect(matchesRule({ input_scenario: ADAPTER }, rule)).toBe(true);
    expect(matchesRule({ input_scenario: FASTA }, rule)).toBe(false);
    expect(matchesRule({ input_scenario: "gctree_forest_pickle" }, rule)).toBe(false);
  });

  it("swaps Root sequence ID for the two new fields when the answer is 'no'", () => {
    const root = visibilityFor("root");
    const rootId = visibilityFor("root_sequence_id");
    const rootSeq = visibilityFor("root_sequence_alignment");

    const carriesRow = { input_scenario: ADAPTER, germline_row_present: "yes" };
    const needsRow = { input_scenario: ADAPTER, germline_row_present: "no" };

    expect(matchesRule(carriesRow, root)).toBe(true);
    expect(matchesRule(carriesRow, rootId)).toBe(false);
    expect(matchesRule(carriesRow, rootSeq)).toBe(false);

    expect(matchesRule(needsRow, root)).toBe(false);
    expect(matchesRule(needsRow, rootId)).toBe(true);
    expect(matchesRule(needsRow, rootSeq)).toBe(true);
  });

  it("leaves the FASTA scenario untouched by the question", () => {
    const root = visibilityFor("root");
    // The question is hidden there, so its value is whatever the default left
    // behind — `root` must not depend on it.
    expect(matchesRule({ input_scenario: FASTA, germline_row_present: "yes" }, root)).toBe(true);
    expect(matchesRule({ input_scenario: FASTA, germline_row_present: "no" }, root)).toBe(true);
    expect(matchesRule({ input_scenario: FASTA }, root)).toBe(true);

    expect(matchesRule({ input_scenario: FASTA }, visibilityFor("root_sequence_id"))).toBe(false);
  });

  it("requires the ID and the sequence only when the row must be added", () => {
    const zod = buildZodSchema(schema, { $inputFormat: "csv" });

    const blank = zod.safeParse({
      input_scenario: ADAPTER,
      germline_row_present: "no",
      root_sequence_id: "",
      root_sequence_alignment: "",
    });
    expect(blank.success).toBe(false);
    if (!blank.success) {
      const fields = blank.error.issues.map((i) => i.path[0]);
      expect(fields).toContain("root_sequence_id");
      expect(fields).toContain("root_sequence_alignment");
    }

    expect(
      zod.safeParse({
        input_scenario: ADAPTER,
        germline_row_present: "no",
        root_sequence_id: "GL",
        root_sequence_alignment: "ACGTACGT",
      }).success,
    ).toBe(true);

    // Table already carries the row: the fields are hidden, so blanks are fine.
    expect(
      zod.safeParse({
        input_scenario: ADAPTER,
        germline_row_present: "yes",
        root: "GL",
        root_sequence_id: "",
        root_sequence_alignment: "",
      }).success,
    ).toBe(true);
  });

  it("rejects an answer outside the yes/no enum", () => {
    const zod = buildZodSchema(schema, { $inputFormat: "csv" });
    expect(
      zod.safeParse({ input_scenario: ADAPTER, germline_row_present: "maybe" }).success,
    ).toBe(false);
  });
});
