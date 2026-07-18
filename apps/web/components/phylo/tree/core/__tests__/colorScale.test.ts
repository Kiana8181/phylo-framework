import { describe, it, expect } from "vitest";
import type { LineagePlot, TreeNodeAttrs } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";
import { buildColorScale, colorForAbundance } from "../colorScale";
import { MAX_CATEGORIES } from "../constants";
import type { TreeModel } from "../types";

/** Build a star model whose leaves carry `attrs[i]`, root = n0. */
function makeModel(
  attrs: Array<Record<string, unknown>>,
  abundances?: number[],
): TreeModel {
  const nodeAttributes: Record<string, TreeNodeAttrs> = {};
  const nodes = [{ id: "n0", label: "n0", x: 0, y: 0, isLeaf: false, abundance: 1 }];
  const edges: LineagePlot["edges"] = [];
  attrs.forEach((a, i) => {
    const id = `n${i + 1}`;
    nodes.push({ id, label: id, x: i + 1, y: i + 1, isLeaf: true, abundance: abundances?.[i] ?? 1 });
    edges.push({ source: "n0", target: id });
    nodeAttributes[id] = a as TreeNodeAttrs;
  });
  return fromLineagePlot({ format: "lineage-plot-v1", nodes, edges }, nodeAttributes);
}

const colorOf = (model: TreeModel, id: string, scale: ReturnType<typeof buildColorScale>) =>
  scale.colorFor(model.nodes.get(id)!);

describe("buildColorScale detection", () => {
  it("treats a low-distinct / non-numeric field as categorical", () => {
    const model = makeModel([{ iso: "IgA" }, { iso: "IgG" }, { iso: "IgM" }, { iso: "IgA" }]);
    const scale = buildColorScale(model, "iso");
    expect(scale.kind).toBe("categorical");
  });

  it("treats a numeric field with many distinct values as continuous", () => {
    const vals = Array.from({ length: 12 }, (_, i) => ({ score: String(i * 3) }));
    const scale = buildColorScale(makeModel(vals), "score");
    expect(scale.kind).toBe("continuous");
  });

  it("abundance is always continuous and reproduces colorForAbundance", () => {
    const abund = [1, 5, 50, 500, 5000];
    const model = makeModel(abund.map(() => ({})), abund);
    const scale = buildColorScale(model, "abundance");
    expect(scale.kind).toBe("continuous");
    // extent across the model (incl. root abundance 1) is [1, 5000].
    for (let i = 0; i < abund.length; i++) {
      expect(colorOf(model, `n${i + 1}`, scale)).toBe(colorForAbundance(abund[i], 1, 5000));
    }
  });
});

describe("buildColorScale categorical", () => {
  it("buckets > MAX_CATEGORIES distinct values into Other", () => {
    const vals = Array.from({ length: MAX_CATEGORIES + 5 }, (_, i) => ({ iso: `v${String(i).padStart(2, "0")}` }));
    const model = makeModel(vals);
    const scale = buildColorScale(model, "iso");
    expect(scale.legend.kind).toBe("categorical");
    if (scale.legend.kind === "categorical") {
      expect(scale.legend.entries.some((e) => e.key === "__other__")).toBe(true);
    }
  });

  it("empty value → unknownColor + hasUnknown; germline → its own token, excluded", () => {
    const model = makeModel([{ iso: "IgA" }, { iso: "" }, { iso: "Germline" }]);
    const scale = buildColorScale(model, "iso", { germlineLabel: "Germline" });
    expect(colorOf(model, "n2", scale)).toBe(scale.unknownColor);
    expect(colorOf(model, "n3", scale)).toBe(scale.germlineColor);
    expect(scale.hasUnknown).toBe(true);
    if (scale.legend.kind === "categorical") {
      expect(scale.legend.entries.some((e) => e.label === "Germline")).toBe(false);
    }
  });
});

describe("buildColorScale cross-panel guarantee", () => {
  it("gives a value the same colour across two different models under a shared domain", () => {
    const domain = ["IgA", "IgD", "IgE", "IgG", "IgM"];
    const modelA = makeModel([{ iso: "IgG" }, { iso: "IgA" }]);
    const modelB = makeModel([{ iso: "IgG" }, { iso: "IgM" }, { iso: "IgE" }]);
    const scaleA = buildColorScale(modelA, "iso", { explicitValues: domain });
    const scaleB = buildColorScale(modelB, "iso", { explicitValues: domain });
    // "IgG" is n1 in both models.
    expect(colorOf(modelA, "n1", scaleA)).toBe(colorOf(modelB, "n1", scaleB));
  });
});
