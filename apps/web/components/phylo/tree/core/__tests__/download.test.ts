import { describe, it, expect } from "vitest";
import { serializeTreeSvg, type NodeVisual, type EdgeVisual } from "../download";

function nodes(n: number): NodeVisual[] {
  return Array.from({ length: n }, (_, i) => ({
    id: `n${i}`,
    cx: i * 10,
    cy: i * 5,
    r: 4,
    fill: "#123456",
    stroke: null,
    strokeWidth: 0,
    hollow: false,
    isMatch: false,
    ringed: false,
    isCollapsible: false,
    faded: false,
    labelShown: i % 2 === 0,
    labelText: `lbl${i}`,
    numberText: null,
  }));
}

const edges: EdgeVisual[] = [{ key: "e0", d: "M 0 0 L 0 5 L 10 5", onPath: false, faded: false }];
const meta = { width: 200, height: 100, labelX: 150, connectorX: 146, strokeWidth: 1 };

describe("serializeTreeSvg (full un-culled export)", () => {
  it("emits a circle for EVERY node passed (un-culled invariant)", () => {
    const svg = serializeTreeSvg(nodes(50), edges, meta);
    expect((svg.match(/<circle/g) ?? []).length).toBe(50);
  });

  it("is independent of any zoom/pan (takes no transform; contains natural coords)", () => {
    const svg = serializeTreeSvg(nodes(5), edges, meta);
    // The far node's natural x is present regardless of on-screen viewport.
    expect(svg).toContain('cx="40"');
    // Root svg is at natural size, no transform attribute anywhere.
    expect(svg).toContain('width="200" height="100"');
    expect(svg).not.toContain("translate(");
  });

  it("draws labels only for label-shown nodes", () => {
    const svg = serializeTreeSvg(nodes(6), edges, meta);
    // i = 0,2,4 → 3 labels; no numberText texts here.
    expect((svg.match(/<text/g) ?? []).length).toBe(3);
  });

  it("exports plain field colour (no interactive match/trace styling)", () => {
    const one = nodes(1);
    one[0].isMatch = true;
    const svg = serializeTreeSvg(one, edges, meta);
    // Match highlighting is interactive focus, not data — export stays plain.
    expect(svg).not.toContain("#dc2626");
    expect(svg).toContain("#123456");
  });

  it("serialises a closed wedge path for each collapsed glyph", () => {
    const glyphs = [
      {
        id: "g0",
        apexX: 24,
        y: 40,
        farX: 220,
        halfHeight: 12,
        fill: "#336699",
        striped: true,
        isMatch: false,
        faded: false,
        labelText: "n=8 · Σ=40",
      },
    ];
    const svg = serializeTreeSvg(nodes(3), edges, meta, glyphs);
    // Wedge paths close with Z (elbow edges do not); the apex/far coords appear.
    expect(svg).toContain("M 24 40 L 220 28 L 220 52 Z");
    expect(svg).toContain("n=8");
  });
});
