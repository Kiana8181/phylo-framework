import { describe, it, expect } from "vitest";
import type { LineagePlot } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";

/** A small, well-formed 5-node tree:
 *      r
 *     / \
 *    a   b
 *   / \
 *  a1  a2
 * Server y encodes clade order: a(20) above b(80); a1(10) above a2(30).
 */
function baseline(): LineagePlot {
  return {
    format: "lineage-plot-v1",
    nodes: [
      { id: "r", label: "r", x: 0, y: 50, isLeaf: false, abundance: 1 },
      { id: "a", label: "a", x: 10, y: 20, isLeaf: false, abundance: 2 },
      { id: "b", label: "b", x: 10, y: 80, isLeaf: true, abundance: 3 },
      { id: "a1", label: "a1", x: 20, y: 10, isLeaf: true, abundance: 4 },
      { id: "a2", label: "a2", x: 20, y: 30, isLeaf: true, abundance: 5 },
    ],
    edges: [
      { source: "r", target: "a" },
      { source: "r", target: "b" },
      { source: "a", target: "a1" },
      { source: "a", target: "a2" },
    ],
  };
}

describe("fromLineagePlot topology", () => {
  it("reproduces the input topology exactly (no node added or removed)", () => {
    const model = fromLineagePlot(baseline());
    expect(model.rootId).toBe("r");
    expect(model.nodes.size).toBe(5);
    expect([...model.order].sort()).toEqual(["a", "a1", "a2", "b", "r"]);

    expect(model.nodes.get("r")!.parentId).toBeNull();
    expect(model.nodes.get("a")!.parentId).toBe("r");
    expect(model.nodes.get("b")!.parentId).toBe("r");
    expect(model.nodes.get("a1")!.parentId).toBe("a");
    expect(model.nodes.get("a2")!.parentId).toBe("a");

    expect(model.nodes.get("r")!.childIds.sort()).toEqual(["a", "b"]);
    expect(model.nodes.get("a")!.childIds.sort()).toEqual(["a1", "a2"]);
    expect(model.nodes.get("b")!.childIds).toEqual([]);
  });

  it("preserves xSource (mutation distance) and ySourceOrder (sort key)", () => {
    const model = fromLineagePlot(baseline());
    expect(model.nodes.get("a1")!.xSource).toBe(20);
    expect(model.nodes.get("a")!.ySourceOrder).toBe(20);
  });

  it("computes subtree aggregates in one pass", () => {
    const model = fromLineagePlot(baseline());
    const r = model.nodes.get("r")!;
    expect(r.subtreeLeafCount).toBe(3);
    expect(r.subtreeNodeCount).toBe(5);
    expect(r.subtreeAbundanceSum).toBe(1 + 2 + 3 + 4 + 5);
    expect(r.subtreeMaxX).toBe(20);
    const a = model.nodes.get("a")!;
    expect(a.subtreeLeafCount).toBe(2);
    expect(a.subtreeNodeCount).toBe(3);
  });
});

describe("fromLineagePlot warnings & root detection", () => {
  it("fires invalid-node-coordinates and drops the node", () => {
    const plot = baseline();
    plot.nodes.push({ id: "bad", label: "bad", x: Number.NaN, y: 5, isLeaf: true });
    const model = fromLineagePlot(plot);
    expect(model.nodes.has("bad")).toBe(false);
    expect(model.warnings.map((w) => w.code)).toContain("invalid-node-coordinates");
  });

  it("fires duplicate-node-id and keeps the first", () => {
    const plot = baseline();
    plot.nodes.push({ id: "a1", label: "dup", x: 99, y: 99, isLeaf: true });
    const model = fromLineagePlot(plot);
    expect(model.nodes.get("a1")!.label).toBe("a1");
    expect(model.warnings.map((w) => w.code)).toContain("duplicate-node-id");
  });

  it("fires missing-edge-node for dangling edges", () => {
    const plot = baseline();
    plot.edges.push({ source: "r", target: "ghost" });
    const model = fromLineagePlot(plot);
    expect(model.warnings.map((w) => w.code)).toContain("missing-edge-node");
  });

  it("fires empty-lineage when there are no renderable nodes", () => {
    const model = fromLineagePlot({ format: "lineage-plot-v1", nodes: [], edges: [] });
    expect(model.nodes.size).toBe(0);
    expect(model.warnings.map((w) => w.code)).toContain("empty-lineage");
  });

  it("honours meta.rootId", () => {
    const plot = baseline();
    plot.meta = { rootId: "a" };
    const model = fromLineagePlot(plot);
    expect(model.rootId).toBe("a");
  });

  it("fires multiple-roots and takes the first in input order", () => {
    const plot: LineagePlot = {
      format: "lineage-plot-v1",
      nodes: [
        { id: "x", label: "x", x: 0, y: 0, isLeaf: true },
        { id: "y", label: "y", x: 0, y: 10, isLeaf: true },
      ],
      edges: [],
    };
    const model = fromLineagePlot(plot);
    expect(model.warnings.map((w) => w.code)).toContain("multiple-roots");
    expect(model.rootId).toBe("x");
  });

  it("builds childIds from parentId when edges are absent", () => {
    const plot: LineagePlot = {
      format: "lineage-plot-v1",
      nodes: [
        { id: "r", label: "r", x: 0, y: 0, isLeaf: false },
        { id: "c", label: "c", x: 1, y: 0, isLeaf: true, parentId: "r" },
      ],
      edges: [],
    };
    const model = fromLineagePlot(plot);
    expect(model.rootId).toBe("r");
    expect(model.nodes.get("r")!.childIds).toEqual(["c"]);
    expect(model.nodes.get("c")!.parentId).toBe("r");
  });
});
