/**
 * Wires the real GCtree contracts JSON to the form logic that consumes it.
 *
 * The `at_abundance` question only works if three separate files agree: the
 * param schema declares the field with no default, ui.json gates it on the
 * `$fastaIdStyle` context key, and the same key makes it required. A typo in any
 * one of them silently drops the question — and then a run with `seq3@9` headers
 * either loses its abundances or dies inside dnapars.
 */
import { describe, expect, it } from "vitest";
import { buildZodSchema, matchesRule } from "@/components/ui/FormBuilder";
import paramSchema from "@phylo/contracts/methods/gctree/param.schema.json";
import uiHints from "@phylo/contracts/methods/gctree/ui.json";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const schema = { ...(paramSchema as any), uiHints } as any;

const visibilityFor = (name: string) =>
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  (uiHints as any).visibility?.[name];

describe("gctree at_abundance contract wiring", () => {
  it("declares the field with no default so it starts unanswered", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const def = (paramSchema as any).properties.at_abundance;
    expect(def).toBeDefined();
    expect(def.enum).toEqual(["yes", "no"]);
    expect(def).not.toHaveProperty("default");
    // Conditionally required, so it must not sit in the global `required` list.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    expect((paramSchema as any).required ?? []).not.toContain("at_abundance");
  });

  it("is listed in the field order and the Input & Mapping section", () => {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const ui = uiHints as any;
    expect(ui.order).toContain("at_abundance");
    const section = ui.sections.find((s: { id: string }) => s.id === "inputMapping");
    expect(section.fields).toContain("at_abundance");
  });

  it("shows the field only for FASTAs that use name@N headers", () => {
    const rule = visibilityFor("at_abundance");
    expect(rule).toBeDefined();
    expect(matchesRule({ $fastaIdStyle: "at_abundance" }, rule)).toBe(true);
    expect(matchesRule({ $fastaIdStyle: "plain" }, rule)).toBe(false);
    expect(matchesRule({ $fastaIdStyle: "other_at" }, rule)).toBe(false);
    // Style not yet resolved (file still being read): stay hidden.
    expect(matchesRule({}, rule)).toBe(false);
  });

  it("blocks submission until answered, but only for name@N FASTAs", () => {
    const withAt = buildZodSchema(schema, {
      $inputFormat: "fasta",
      $fastaIdStyle: "at_abundance",
    });
    const unanswered = withAt.safeParse({ input_scenario: "aligned_fasta_with_root" });
    expect(unanswered.success).toBe(false);
    if (!unanswered.success) {
      expect(unanswered.error.issues.some((i) => i.path[0] === "at_abundance")).toBe(true);
    }
    expect(
      withAt.safeParse({ input_scenario: "aligned_fasta_with_root", at_abundance: "yes" })
        .success,
    ).toBe(true);

    const plain = buildZodSchema(schema, { $inputFormat: "fasta", $fastaIdStyle: "plain" });
    expect(plain.safeParse({ input_scenario: "aligned_fasta_with_root" }).success).toBe(true);
  });

  it("rejects an answer outside the yes/no enum", () => {
    const withAt = buildZodSchema(schema, { $fastaIdStyle: "at_abundance" });
    expect(
      withAt.safeParse({ input_scenario: "aligned_fasta_with_root", at_abundance: "maybe" })
        .success,
    ).toBe(false);
  });
});
