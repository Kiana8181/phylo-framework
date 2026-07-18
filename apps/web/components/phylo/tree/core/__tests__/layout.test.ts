import { describe, it, expect } from "vitest";
import type { LineagePlot } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";
import { layoutTree } from "../layout";
import { ROW_GAP, PAD } from "../constants";
import type { TreeNodeModel } from "../types";

/** Tree with abundances chosen to span the full radius range (3…24). */
function spread(): LineagePlot {
  return {
    format: "lineage-plot-v1",
    nodes: [
      { id: "r", label: "r", x: 0, y: 50, isLeaf: false, abundance: 1 },
      { id: "a", label: "a", x: 10, y: 20, isLeaf: false, abundance: 1 },
      { id: "b", label: "b", x: 10, y: 80, isLeaf: true, abundance: 5 },
      { id: "a1", label: "a1", x: 20, y: 10, isLeaf: true, abundance: 1 },
      { id: "a2", label: "a2", x: 20, y: 30, isLeaf: true, abundance: 5000 },
    ],
    edges: [
      { source: "r", target: "a" },
      { source: "r", target: "b" },
      { source: "a", target: "a1" },
      { source: "a", target: "a2" },
    ],
  };
}

const opts = {
  showLabels: true,
  showInternalNodes: false,
  displayLabelOf: (n: TreeNodeModel) => n.label,
};

describe("layoutTree packing", () => {
  it("satisfies the no-overlap invariant across adjacent visible slots", () => {
    const layout = layoutTree(fromLineagePlot(spread()), opts);
    const leaves = layout.nodes.filter((n) => n.isLeaf).sort((p, q) => p.y - q.y);
    expect(leaves.length).toBeGreaterThan(1);
    for (let i = 0; i + 1 < leaves.length; i++) {
      const gap = leaves[i + 1].y - leaves[i].y;
      const bound = leaves[i].radius + leaves[i + 1].radius + ROW_GAP;
      // +epsilon: packing and the assertion sum the same terms in a different
      // order, so they can differ by 1 ULP. The invariant is >= mathematically.
      expect(gap + 1e-9).toBeGreaterThanOrEqual(bound);
    }
  });

  it("orders visible leaves by server y ascending", () => {
    const model = fromLineagePlot(spread());
    const layout = layoutTree(model, opts);
    const leafIdsByY = layout.nodes
      .filter((n) => n.isLeaf)
      .sort((p, q) => p.y - q.y)
      .map((n) => n.id);
    const expected = [...model.nodes.values()]
      .filter((n) => n.isLeaf)
      .sort((p, q) => (p.ySourceOrder ?? 0) - (q.ySourceOrder ?? 0))
      .map((n) => n.id);
    expect(leafIdsByY).toEqual(expected);
  });
});

describe("layoutTree x/y mapping", () => {
  it("maps x through a single affine transform (min node at PAD, monotonic)", () => {
    const layout = layoutTree(fromLineagePlot(spread()), opts);
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    // r has the smallest xSource (0) → xPixel === PAD.
    expect(byId.get("r")!.xPixel).toBeCloseTo(PAD, 5);
    // Larger xSource → larger xPixel.
    expect(byId.get("a1")!.xPixel).toBeGreaterThan(byId.get("a")!.xPixel);
    expect(byId.get("a")!.xPixel).toBeGreaterThan(byId.get("r")!.xPixel);
  });

  it("places an internal node at the midpoint of its first & last child", () => {
    const layout = layoutTree(fromLineagePlot(spread()), opts);
    const byId = new Map(layout.nodes.map((n) => [n.id, n]));
    const a1 = byId.get("a1")!;
    const a2 = byId.get("a2")!;
    expect(byId.get("a")!.y).toBeCloseTo((a1.y + a2.y) / 2, 5);
    // root sits between its first (a) and last (b) visible children.
    const a = byId.get("a")!;
    const b = byId.get("b")!;
    expect(byId.get("r")!.y).toBeCloseTo((a.y + b.y) / 2, 5);
  });

  it("never changes node count between model and layout (no collapse)", () => {
    const model = fromLineagePlot(spread());
    const layout = layoutTree(model, opts);
    expect(layout.nodes.length).toBe(model.nodes.size);
  });

  it("fills the width even when the total x-span is < 1 (fractional branch lengths)", () => {
    // Regression: a divisor clamped to Math.max(1, span) crushed phylogeny trees,
    // whose branch-length spans are tiny decimals (e.g. 0.15 total).
    const tiny: LineagePlot = {
      format: "lineage-plot-v1",
      nodes: [
        { id: "r", label: "r", x: 0, y: 0, isLeaf: false, abundance: 1 },
        { id: "a", label: "a", x: 0.05, y: 10, isLeaf: true, abundance: 1 },
        { id: "b", label: "b", x: 0.15, y: 20, isLeaf: true, abundance: 1 },
      ],
      edges: [
        { source: "r", target: "a" },
        { source: "r", target: "b" },
      ],
    };
    const layout = layoutTree(fromLineagePlot(tiny), { ...opts, targetWidth: 960 });
    const maxX = Math.max(...layout.nodes.map((n) => n.xPixel));
    // With the bug this was ~168 (0.15*960 + PAD); fixed it fills ~PAD + 960.
    expect(maxX).toBeGreaterThan(900);
  });
});

describe("layoutTree collapse", () => {
  it("collapsing a node never changes any surviving node's xPixel", () => {
    const model = fromLineagePlot(spread());
    const expanded = layoutTree(model, opts);
    const collapsed = layoutTree(model, { ...opts, collapsed: new Set(["a"]) });
    const xExpanded = new Map(expanded.nodes.map((n) => [n.id, n.xPixel]));
    for (const n of collapsed.nodes) {
      expect(n.xPixel).toBeCloseTo(xExpanded.get(n.id)!, 6);
    }
  });

  it("collapsing removes descendants and exposes wedge geometry", () => {
    const model = fromLineagePlot(spread());
    const layout = layoutTree(model, { ...opts, collapsed: new Set(["a"]) });
    const ids = new Set(layout.nodes.map((n) => n.id));
    // a's descendants (a1, a2) are gone; a itself is a collapsed wedge.
    expect(ids.has("a1")).toBe(false);
    expect(ids.has("a2")).toBe(false);
    const a = layout.nodes.find((n) => n.id === "a")!;
    expect(a.isCollapsed).toBe(true);
    expect(typeof a.glyphFarXPixel).toBe("number");
    expect(typeof a.glyphHalfHeight).toBe("number");
    // The wedge reaches the subtree's far x (a2 is at xSource 20, the max).
    expect(a.glyphFarXPixel!).toBeGreaterThan(a.xPixel);
  });

  it("expandAll layout is node-for-node identical to the fully-expanded layout", () => {
    const model = fromLineagePlot(spread());
    const base = layoutTree(model, opts);
    const viaEmpty = layoutTree(model, { ...opts, collapsed: new Set() });
    expect(viaEmpty.nodes.length).toBe(base.nodes.length);
    const byId = new Map(base.nodes.map((n) => [n.id, n]));
    for (const n of viaEmpty.nodes) {
      const b = byId.get(n.id)!;
      expect(n.xPixel).toBeCloseTo(b.xPixel, 6);
      expect(n.y).toBeCloseTo(b.y, 6);
      expect(n.isCollapsed).toBe(false);
    }
  });
});
