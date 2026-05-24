import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import path from "node:path";

const repoRoot = path.resolve(__dirname, "../../../../..");
const uiPath = path.join(repoRoot, "packages/contracts/methods/dowser/ui.json");
const paramPath = path.join(repoRoot, "packages/contracts/methods/dowser/param.schema.json");

type VisibilityRule = {
  when?: Record<string, unknown>;
  whenAll?: Array<Record<string, unknown>>;
  whenAny?: Array<Record<string, unknown>>;
};

function testWhen(values: Record<string, unknown>, cond: Record<string, unknown>) {
  return Object.entries(cond).every(([k, expected]) => {
    const v = values[k];
    return Array.isArray(expected) ? expected.includes(v) : v === expected;
  });
}

function isFieldVisible(visibility: Record<string, VisibilityRule>, name: string, values: Record<string, unknown>) {
  const vis = visibility[name];
  if (!vis) return true;
  if (vis.when) return testWhen(values, vis.when);
  if (vis.whenAll) return vis.whenAll.every((c) => testWhen(values, c));
  if (vis.whenAny) return vis.whenAny.some((c) => testWhen(values, c));
  return true;
}

describe("FormBuilder Dowser conditional fields", () => {
  const ui = JSON.parse(readFileSync(uiPath, "utf8")) as { visibility?: Record<string, VisibilityRule>; order?: string[] };
  const param = JSON.parse(readFileSync(paramPath, "utf8")) as {
    properties: Record<string, { enum?: string[] }>;
  };
  const visibility = ui.visibility ?? {};

  it("does not include removed filter fields in order", () => {
    expect(ui.order).not.toContain("apply_filters");
    expect(ui.order).not.toContain("gap_policy");
    expect(param.properties.apply_filters).toBeUndefined();
  });

  it("renders all tree build methods", () => {
    expect(param.properties.tree_build.enum).toEqual([
      "pratchet",
      "pml",
      "dnapars",
      "dnaml",
      "igphyml",
      "raxml",
    ]);
  });

  it("shows DTA fields only when DTA mode enabled", () => {
    expect(isFieldVisible(visibility, "trait_field", { analysis_mode: "discrete_trait_analysis" })).toBe(true);
    expect(isFieldVisible(visibility, "trait_field", { analysis_mode: "tree_only" })).toBe(false);
  });

  it("shows IgPhyML options only when tree_build is igphyml", () => {
    expect(isFieldVisible(visibility, "partition_model", { tree_build: "igphyml" })).toBe(true);
    expect(isFieldVisible(visibility, "partition_model", { tree_build: "pml" })).toBe(false);
  });

  it("does not expose duplicate R-side column override params", () => {
    expect(param.properties.sequence_column).toBeUndefined();
    expect(param.properties.id_column).toBeUndefined();
    expect(param.properties.cell_id_column).toBeUndefined();
    expect(param.properties.column_map.properties.cell_id).toBeDefined();
  });

  it("shows HL column mapping when doMapping and chain_mode HL", () => {
    expect(
      isFieldVisible(visibility, "column_map.cell_id", { doMapping: true, chain_mode: "HL" }),
    ).toBe(true);
    expect(isFieldVisible(visibility, "column_map.cell_id", { doMapping: false, chain_mode: "HL" })).toBe(
      false,
    );
  });
});
