import { describe, it, expect } from "vitest";
import type { LineagePlot } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";
import { computeTrace, deriveTraceCollapsed } from "../trace";

// root n0 ─ n1 ─ n2 ─ n3(leaf, MATCH)
//        └ n4 ─ n5(leaf)   (off-path branch)
function fixture() {
  const nodes: LineagePlot["nodes"] = [
    { id: "n0", label: "n0", x: 0, y: 0, isLeaf: false, abundance: 1 },
    { id: "n1", label: "n1", x: 1, y: 1, isLeaf: false, abundance: 1 },
    { id: "n2", label: "n2", x: 2, y: 2, isLeaf: false, abundance: 1 },
    { id: "n3", label: "n3", x: 3, y: 3, isLeaf: true, abundance: 1 },
    { id: "n4", label: "n4", x: 1, y: 4, isLeaf: false, abundance: 1 },
    { id: "n5", label: "n5", x: 2, y: 5, isLeaf: true, abundance: 1 },
  ];
  const edges: LineagePlot["edges"] = [
    { source: "n0", target: "n1" },
    { source: "n1", target: "n2" },
    { source: "n2", target: "n3" },
    { source: "n0", target: "n4" },
    { source: "n4", target: "n5" },
  ];
  return fromLineagePlot({ format: "lineage-plot-v1", nodes, edges });
}

describe("computeTrace", () => {
  it("computes the root→match path and the match subtree", () => {
    const model = fixture();
    const { pathIds, subtreeIds } = computeTrace(model, new Set(["n3"]));
    expect([...pathIds].sort()).toEqual(["n0", "n1", "n2", "n3"]);
    expect([...subtreeIds].sort()).toEqual(["n3"]);
  });

  it("unions paths and subtrees over multiple matches", () => {
    const model = fixture();
    const { pathIds, subtreeIds } = computeTrace(model, new Set(["n3", "n5"]));
    expect([...pathIds].sort()).toEqual(["n0", "n1", "n2", "n3", "n4", "n5"]);
    expect([...subtreeIds].sort()).toEqual(["n3", "n5"]);
  });
});

describe("deriveTraceCollapsed", () => {
  it("force-expands the path, collapses off-path siblings, and never mutates the user set", () => {
    const model = fixture();
    const { pathIds, subtreeIds } = computeTrace(model, new Set(["n3"]));
    const userCollapsed = new Set(["n1"]); // user had a path node collapsed
    const result = deriveTraceCollapsed(model, userCollapsed, pathIds, subtreeIds);

    expect(result.has("n1")).toBe(false); // path force-expanded
    expect(result.has("n4")).toBe(true); // off-path sibling collapsed
    // user's own set is untouched
    expect([...userCollapsed]).toEqual(["n1"]);
  });

  it("leaves a leaf sibling alone (nothing to collapse)", () => {
    const model = fixture();
    // match n5 → path n0,n4,n5; n1 is an off-path INTERNAL sibling of n0 → collapses.
    const { pathIds, subtreeIds } = computeTrace(model, new Set(["n5"]));
    const result = deriveTraceCollapsed(model, new Set(), pathIds, subtreeIds);
    expect(result.has("n1")).toBe(true);
  });
});
