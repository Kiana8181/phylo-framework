import { describe, it, expect } from "vitest";
import type { LineagePlot, TreeNodeAttrs } from "@phylo/contracts";
import { fromLineagePlot } from "../fromLineagePlot";
import { computeMatchIds } from "../match";

// root n0 ─ n1(leaf, "IGH001")
//        └ n2(leaf, "IGH0011")   <- prefix-extended; must NOT match "IGH001"
//        └ n3(leaf, label "x9", attrs.sequence_id "IGH777")
function fixture(nodeAttributes?: Record<string, TreeNodeAttrs>) {
  const nodes: LineagePlot["nodes"] = [
    { id: "n0", label: "germline", x: 0, y: 0, isLeaf: false, abundance: 1 },
    { id: "n1", label: "IGH001", x: 1, y: 1, isLeaf: true, abundance: 1 },
    { id: "n2", label: "IGH0011", x: 1, y: 2, isLeaf: true, abundance: 1 },
    { id: "n3", label: "x9", x: 1, y: 3, isLeaf: true, abundance: 1 },
  ];
  const edges: LineagePlot["edges"] = [
    { source: "n0", target: "n1" },
    { source: "n0", target: "n2" },
    { source: "n0", target: "n3" },
  ];
  return fromLineagePlot({ format: "lineage-plot-v1", nodes, edges }, nodeAttributes);
}

const phylo = { isLineage: false } as const;
const lineage = { isLineage: true } as const;

describe("computeMatchIds — exact identifier matching", () => {
  it("matches the whole label and not a longer label sharing the prefix", () => {
    const model = fixture();
    const ids = computeMatchIds(model, "IGH001", phylo);
    expect([...ids]).toEqual(["n1"]);
    expect(ids.has("n2")).toBe(false); // IGH0011 must not match IGH001
  });

  it("is case-insensitive and trims surrounding whitespace", () => {
    const model = fixture();
    expect([...computeMatchIds(model, "  igh001  ", phylo)]).toEqual(["n1"]);
    expect([...computeMatchIds(model, "IgH001", phylo)]).toEqual(["n1"]);
  });

  it("returns no matches when no identifier equals the query", () => {
    const model = fixture();
    expect(computeMatchIds(model, "IGH0", phylo).size).toBe(0); // prefix
    expect(computeMatchIds(model, "GH001", phylo).size).toBe(0); // infix
    expect(computeMatchIds(model, "nope", phylo).size).toBe(0);
    expect(computeMatchIds(model, "", phylo).size).toBe(0);
    expect(computeMatchIds(model, "   ", phylo).size).toBe(0);
  });

  it("matches on the sequence_id attribute when the tree label differs", () => {
    const model = fixture({ n3: { sequence_id: "IGH777" } });
    expect([...computeMatchIds(model, "IGH777", phylo)]).toEqual(["n3"]);
    expect([...computeMatchIds(model, "x9", phylo)]).toEqual(["n3"]);
  });

  it("scopes by view: phylogeny matches leaves only, lineage matches any node", () => {
    const model = fixture();
    expect(computeMatchIds(model, "germline", phylo).size).toBe(0);
    expect([...computeMatchIds(model, "germline", lineage)]).toEqual(["n0"]);
  });

  it("returns every node sharing an identifier, without preferring the first", () => {
    const model = fixture({ n2: { sequence_id: "IGH001" } });
    expect([...computeMatchIds(model, "IGH001", phylo).values()].sort()).toEqual(["n1", "n2"]);
  });
});

// root n0 ─ n1(leaf, "id1|id2|id3")
//        └ n2(leaf, "other|id20")   <- id2 is a prefix of id20; must NOT match
function pipeFixture(nodeAttributes?: Record<string, TreeNodeAttrs>) {
  const nodes: LineagePlot["nodes"] = [
    { id: "n0", label: "germline", x: 0, y: 0, isLeaf: false, abundance: 1 },
    { id: "n1", label: "id1|id2|id3", x: 1, y: 1, isLeaf: true, abundance: 1 },
    { id: "n2", label: "other|id20", x: 1, y: 2, isLeaf: true, abundance: 1 },
  ];
  const edges: LineagePlot["edges"] = [
    { source: "n0", target: "n1" },
    { source: "n0", target: "n2" },
  ];
  return fromLineagePlot({ format: "lineage-plot-v1", nodes, edges }, nodeAttributes);
}

describe("computeMatchIds — pipe-delimited identifiers", () => {
  it("matches any single |-separated part", () => {
    const model = pipeFixture();
    expect([...computeMatchIds(model, "id1", phylo)]).toEqual(["n1"]);
    expect([...computeMatchIds(model, "id2", phylo)]).toEqual(["n1"]);
    expect([...computeMatchIds(model, "id3", phylo)]).toEqual(["n1"]);
  });

  it("still matches the whole pipe-delimited identifier", () => {
    const model = pipeFixture();
    expect([...computeMatchIds(model, "id1|id2|id3", phylo)]).toEqual(["n1"]);
    expect([...computeMatchIds(model, "  ID1|Id2|id3 ", phylo)]).toEqual(["n1"]);
  });

  it("keeps each part exact — no prefix or infix hits", () => {
    const model = pipeFixture();
    expect(computeMatchIds(model, "id", phylo).size).toBe(0);
    expect(computeMatchIds(model, "id2|id3", phylo).size).toBe(0); // partial run of parts
    expect(computeMatchIds(model, "id2", phylo).has("n2")).toBe(false); // id20 ≠ id2
  });

  it("matches parts of a pipe-delimited sequence_id attribute", () => {
    const model = pipeFixture({ n2: { sequence_id: "alpha|beta" } });
    expect([...computeMatchIds(model, "beta", phylo)]).toEqual(["n2"]);
  });

  it("ignores whitespace padding around parts", () => {
    const model = pipeFixture({ n2: { sequence_id: "alpha | beta" } });
    expect([...computeMatchIds(model, "beta", phylo)]).toEqual(["n2"]);
  });
});
