import { describe, expect, it } from "vitest";
import { buildZodSchema } from "@/components/ui/FormBuilder";

// The schema shape mirrors what RunParameters passes: param schema props plus
// a merged `uiHints` carrying the declarative validation block.
const brepphyloLikeSchema = {
  type: "object",
  properties: {
    min_clone_size: { type: "integer", minimum: 1, default: 10 },
    species: { type: "string", enum: ["human", "custom"] },
    germline_set_text: { type: "string" },
    enable_csr_analysis: { type: "boolean" },
    isotype_column: { type: "string" },
    which_clones: { type: "string" },
    ignore_clones: { type: "string" },
  },
  uiHints: {
    validation: {
      requiredWhen: [
        { field: "germline_set_text", when: { species: "custom" }, message: "germline required" },
        { field: "isotype_column", when: { enable_csr_analysis: true }, message: "isotype required" },
      ],
      mutuallyExclusive: [
        { fields: ["which_clones", "ignore_clones"], message: "mutually exclusive" },
      ],
    },
  },
} as const;

function errorsByField(schema: ReturnType<typeof buildZodSchema>, data: Record<string, unknown>) {
  const result = schema.safeParse(data);
  if (result.success) return {} as Record<string, string[]>;
  const out: Record<string, string[]> = {};
  for (const issue of result.error.issues) {
    const key = issue.path.join(".");
    (out[key] ??= []).push(issue.message);
  }
  return out;
}

describe("buildZodSchema", () => {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const schema = buildZodSchema(brepphyloLikeSchema as any);

  it("enforces numeric minimum from the param schema", () => {
    expect(errorsByField(schema, { min_clone_size: 0 })).toHaveProperty("min_clone_size");
    expect(schema.safeParse({ min_clone_size: 5 }).success).toBe(true);
  });

  it("requires germline_set_text only when species is custom", () => {
    expect(errorsByField(schema, { species: "custom" })["germline_set_text"]).toContain(
      "germline required",
    );
    expect(schema.safeParse({ species: "human" }).success).toBe(true);
    expect(schema.safeParse({ species: "custom", germline_set_text: ">x" }).success).toBe(true);
  });

  it("requires isotype_column only when CSR analysis is enabled", () => {
    expect(errorsByField(schema, { enable_csr_analysis: true })["isotype_column"]).toContain(
      "isotype required",
    );
    expect(schema.safeParse({ enable_csr_analysis: false }).success).toBe(true);
  });

  it("flags both fields when mutually exclusive inputs are both set", () => {
    const errors = errorsByField(schema, { which_clones: "c1", ignore_clones: "c2" });
    expect(errors["which_clones"]).toContain("mutually exclusive");
    expect(errors["ignore_clones"]).toContain("mutually exclusive");
    expect(schema.safeParse({ which_clones: "c1" }).success).toBe(true);
  });
});
