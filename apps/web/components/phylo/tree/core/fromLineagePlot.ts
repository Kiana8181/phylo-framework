import type { LineagePlot, LineagePlotNode, TreeNodeAttrs } from "@phylo/contracts";
import type { LayoutWarning, TreeModel } from "./types";
import { isFiniteNumber, toAbundance } from "./math";
import { assignOrderAndDepth, computeAggregates, type MutableNode } from "./model";

function resolveNodeAttrs(
  node: LineagePlotNode,
  nodeAttributes?: Record<string, TreeNodeAttrs>,
): TreeNodeAttrs | undefined {
  return nodeAttributes?.[node.label] ?? nodeAttributes?.[node.id];
}

/**
 * Adapt a server `LineagePlot` into the renderer-agnostic `TreeModel`.
 *
 * Validation is a behaviour-preserving port of the original LineageSVG
 * `buildLayout`: same warning codes/messages, same drop semantics. Topology is
 * built from `edges`, falling back to each node's `parentId` where an edge is
 * absent. `xSource = node.x` (mutation distance, preserved). `ySourceOrder =
 * node.y` (sort key only). No node is added or removed beyond the documented
 * validation drops.
 */
export function fromLineagePlot(
  lineagePlot: LineagePlot,
  nodeAttributes?: Record<string, TreeNodeAttrs>,
): TreeModel {
  const warnings: LayoutWarning[] = [];
  let invalidNodeCount = 0;
  let duplicateNodeCount = 0;
  let missingEdgeNodeCount = 0;

  // 1) Drop nodes with invalid coordinates (verbatim rule).
  const cleanNodes = (lineagePlot.nodes ?? []).filter((node) => {
    const valid = isFiniteNumber(node.x) && isFiniteNumber(node.y);
    if (!valid) invalidNodeCount += 1;
    return valid;
  });

  // 2) Dedupe by id, keeping the first.
  const byId = new Map<string, LineagePlotNode>();
  const inputOrder: string[] = [];
  for (const node of cleanNodes) {
    if (byId.has(node.id)) {
      duplicateNodeCount += 1;
      continue;
    }
    byId.set(node.id, node);
    inputOrder.push(node.id);
  }

  // 3) Keep only edges whose endpoints both exist.
  const edges = (lineagePlot.edges ?? []).filter((edge) => {
    const valid = byId.has(edge.source) && byId.has(edge.target);
    if (!valid) missingEdgeNodeCount += 1;
    return valid;
  });

  if (invalidNodeCount > 0) {
    warnings.push({
      code: "invalid-node-coordinates",
      message: "Dropped lineage nodes with missing/invalid coordinates.",
      details: { droppedNodes: invalidNodeCount },
    });
  }
  if (duplicateNodeCount > 0) {
    warnings.push({
      code: "duplicate-node-id",
      message: "Duplicate lineage node IDs detected; only the first duplicate was rendered.",
      details: { droppedNodes: duplicateNodeCount },
    });
  }
  if (missingEdgeNodeCount > 0) {
    warnings.push({
      code: "missing-edge-node",
      message: "Dropped lineage edges that reference missing nodes.",
      details: { droppedEdges: missingEdgeNodeCount },
    });
  }

  if (byId.size === 0) {
    warnings.push({ code: "empty-lineage", message: "Lineage plot has no renderable nodes." });
    return { rootId: "", nodes: new Map(), order: [], warnings };
  }

  // 4) Parent/child relationships: edges first, then parentId fallback.
  const parentOf = new Map<string, string>();
  const childrenOf = new Map<string, string[]>();
  const pushChild = (parent: string, child: string) => {
    const list = childrenOf.get(parent);
    if (list) list.push(child);
    else childrenOf.set(parent, [child]);
  };
  for (const edge of edges) {
    if (parentOf.has(edge.target)) continue; // first parent wins
    parentOf.set(edge.target, edge.source);
    pushChild(edge.source, edge.target);
  }
  for (const id of inputOrder) {
    if (parentOf.has(id)) continue;
    const p = byId.get(id)?.parentId;
    if (p && byId.has(p) && p !== id) {
      parentOf.set(id, p);
      pushChild(p, id);
    }
  }

  // 5) Root detection.
  const noParent = inputOrder.filter((id) => !parentOf.has(id));
  let rootId: string;
  const metaRoot = lineagePlot.meta?.rootId;
  if (metaRoot && byId.has(metaRoot)) {
    rootId = metaRoot;
  } else if (noParent.length <= 1) {
    rootId = noParent[0] ?? inputOrder[0];
  } else {
    warnings.push({
      code: "multiple-roots",
      message: "Lineage plot has multiple roots; using the first in input order.",
      details: { rootCount: noParent.length },
    });
    rootId = noParent[0];
  }

  // 6) Build node models (topology + source coords + abundance + attrs).
  const nodes = new Map<string, MutableNode>();
  for (const id of inputOrder) {
    const src = byId.get(id)!;
    const attrs = resolveNodeAttrs(src, nodeAttributes);
    nodes.set(id, {
      id,
      label: src.label,
      parentId: parentOf.get(id) ?? null,
      childIds: childrenOf.get(id) ?? [],
      isLeaf: src.isLeaf,
      depth: 0,
      xSource: src.x,
      ySourceOrder: src.y,
      abundance: toAbundance(src.abundance ?? attrs?.abundance),
      attrs,
      subtreeLeafCount: 0,
      subtreeNodeCount: 0,
      subtreeAbundanceSum: undefined,
      subtreeMaxX: src.x,
    });
  }

  // xSource is already set from the server; order/depth then aggregates.
  const order = assignOrderAndDepth(nodes, rootId, inputOrder);
  computeAggregates(nodes, order);
  return { rootId, nodes, order, warnings };
}
