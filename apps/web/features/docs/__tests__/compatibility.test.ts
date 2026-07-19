import { describe, expect, it } from "vitest";
import { buildCompatibilityModel, getUniversalColumns } from "../compatibility";
import { getLoadedMethod } from "../loader";
import { METHOD_IDS } from "../types";

function acceptedColumns(id: (typeof METHOD_IDS)[number]): Set<string> {
  const m = getLoadedMethod(id);
  const cols = new Set<string>();
  const columnMap = (m.paramSchema.properties?.column_map?.properties ?? {}) as Record<string, unknown>;
  for (const key of Object.keys(columnMap)) cols.add(key);
  // BrepPhylo's flat columns, mapped to their AIRR canonicals.
  const flatToAirr: Record<string, string> = {
    sequence_column: "sequence_alignment",
    clone_id_column: "clone_id",
    germline_id_column: "germline_alignment_d_mask",
    label_column: "sequence_id",
    isotype_column: "c_call",
  };
  for (const [flat, canonical] of Object.entries(flatToAirr)) {
    if (m.paramSchema.properties?.[flat]) cols.add(canonical);
  }
  return cols;
}

describe("getUniversalColumns", () => {
  const universal = getUniversalColumns();

  it("is a subset of every method's accepted columns", () => {
    for (const id of METHOD_IDS) {
      const accepted = acceptedColumns(id);
      for (const col of universal) {
        expect(accepted.has(col), `${col} should be accepted by ${id}`).toBe(true);
      }
    }
  });

  it("includes sequence_id and sequence_alignment (the shared core)", () => {
    expect(universal).toContain("sequence_id");
    expect(universal).toContain("sequence_alignment");
  });

  it("is derived, not hardcoded — never contains a column gctree lacks", () => {
    const gctree = acceptedColumns("gctree");
    for (const col of universal) expect(gctree.has(col)).toBe(true);
  });
});

describe("buildCompatibilityModel", () => {
  const model = buildCompatibilityModel();
  const byColumn = new Map(model.map((row) => [row.column, row]));

  it("classifies a column required by BrepPhylo and unused by GCtree correctly", () => {
    const germline = byColumn.get("germline_alignment_d_mask");
    expect(germline).toBeDefined();
    expect(germline!.byMethod.brepphylo).toBe("required");
    expect(germline!.byMethod.gctree).toBe("not-used");
    // dowser requires it too (from columns.json core group).
    expect(germline!.byMethod.dowser).toBe("required");
  });

  it("marks the core data columns as required (from columns.json, not param.schema)", () => {
    // sequence_id / sequence_alignment are required inputs for the mapping methods.
    for (const col of ["sequence_id", "sequence_alignment"]) {
      const row = byColumn.get(col);
      expect(row).toBeDefined();
      expect(row!.byMethod.dowser, `${col} dowser`).toBe("required");
      expect(row!.byMethod.gctree, `${col} gctree`).toBe("required");
      expect(row!.byMethod.clonaltree, `${col} clonaltree`).toBe("required");
    }
    // clonaltree base column that dowser does not use at all.
    const junctionAa = byColumn.get("junction_aa");
    expect(junctionAa!.byMethod.clonaltree).toBe("required");
    expect(junctionAa!.byMethod.dowser).toBe("not-used");
  });

  it("keeps genuinely optional columns optional", () => {
    // dowser accepts `junction` via column_map but never requires it.
    const junction = byColumn.get("junction");
    expect(junction!.byMethod.dowser).toBe("optional");
  });

  it("marks universal columns as used (never not-used) by every method", () => {
    for (const col of getUniversalColumns()) {
      const row = byColumn.get(col);
      expect(row).toBeDefined();
      for (const id of METHOD_IDS) {
        expect(row!.byMethod[id], `${col} in ${id}`).not.toBe("not-used");
      }
    }
  });

  it("captures a biological conditional gate as conditional (not the doMapping wrapper gate)", () => {
    // dowser cell_id/locus are gated on chain_mode = HL.
    const cellId = byColumn.get("cell_id");
    expect(cellId).toBeDefined();
    expect(cellId!.byMethod.dowser).toBe("conditional");
    expect(cellId!.conditionNote).toBeTruthy();
    expect(cellId!.conditionNote).not.toMatch(/doMapping/i);
  });

  it("emits exactly one row per canonical column with a status for all four methods", () => {
    const columns = model.map((r) => r.column);
    expect(new Set(columns).size).toBe(columns.length);
    for (const row of model) {
      for (const id of METHOD_IDS) expect(row.byMethod[id]).toBeDefined();
    }
  });
});
