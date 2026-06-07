import { describe, expect, it } from "vitest";
import { computeNodes, sanitizeLabel } from "../runStageNodes";

describe("computeNodes", () => {
  it("marks earlier stages done, current active, later pending", () => {
    const nodes = computeNodes("gctree", "RUNNING", "BUILDING_TREES");
    const active = nodes.filter((n) => n.state === "active");
    expect(active).toHaveLength(1);
    expect(active[0].id).toBe("BUILDING_TREES");

    const activeIdx = nodes.findIndex((n) => n.id === "BUILDING_TREES");
    expect(nodes.slice(0, activeIdx).every((n) => n.state === "done")).toBe(true);
    expect(nodes.slice(activeIdx + 1).every((n) => n.state === "pending")).toBe(true);
  });

  it("marks every node done when the run is DONE", () => {
    const nodes = computeNodes("dowser", "DONE", "COMPLETED");
    expect(nodes.every((n) => n.state === "done")).toBe(true);
  });

  it("represents ERROR without implying success", () => {
    const nodes = computeNodes("gctree", "ERROR", "BUILDING_TREES");
    expect(nodes.some((n) => n.state === "error")).toBe(true);
    // The COMPLETED node must not be marked done on failure.
    const completed = nodes.find((n) => n.id === "COMPLETED");
    expect(completed?.state).not.toBe("done");
  });

  it("represents CANCELLING/CANCELLED clearly", () => {
    const cancelling = computeNodes("gctree", "RUNNING", "CANCELLING");
    expect(cancelling.some((n) => n.state === "cancelled")).toBe(true);

    const cancelled = computeNodes("gctree", "CANCELLED", "CANCELLED");
    expect(cancelled.some((n) => n.state === "cancelled")).toBe(true);
    const completed = cancelled.find((n) => n.id === "COMPLETED");
    expect(completed?.state).not.toBe("done");
  });

  it("tolerates an unknown method-reported stage by inserting it", () => {
    const nodes = computeNodes("gctree", "RUNNING", "SOME_CUSTOM_STEP");
    const inserted = nodes.find((n) => n.id === "SOME_CUSTOM_STEP");
    expect(inserted).toBeDefined();
    expect(inserted?.state).toBe("active");
  });

  it("falls back to the common sequence for unknown methods", () => {
    const nodes = computeNodes("unknown-method", "QUEUED", "QUEUED");
    expect(nodes[0].id).toBe("QUEUED");
    expect(nodes[0].state).toBe("active");
  });
});

describe("sanitizeLabel", () => {
  it("removes characters that would break Mermaid syntax", () => {
    expect(sanitizeLabel('Build "trees" <x> {y} |z|')).toBe("Build trees x y z");
  });

  it("collapses whitespace and truncates long labels", () => {
    const long = "a".repeat(80);
    expect(sanitizeLabel(long).length).toBe(40);
  });
});
