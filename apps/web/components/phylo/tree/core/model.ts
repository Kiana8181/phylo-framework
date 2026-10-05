import type { TreeNodeModel } from "./types";

export type MutableNode = TreeNodeModel;

/**
 * Assign `depth` and produce a stable DFS pre-order over ALL nodes. Visits the
 * root's component first, then any stragglers in input order so that no node is
 * ever dropped from `order`. Iterative to survive deep linear trees.
 */
export function assignOrderAndDepth(
  nodes: Map<string, MutableNode>,
  rootId: string,
  inputOrder: string[],
): string[] {
  const order: string[] = [];
  const visited = new Set<string>();

  const preorder = (startId: string, startDepth: number) => {
    const stack: Array<{ id: string; depth: number }> = [{ id: startId, depth: startDepth }];
    while (stack.length) {
      const { id, depth } = stack.pop()!;
      const node = nodes.get(id);
      if (!node || visited.has(id)) continue;
      visited.add(id);
      node.depth = depth;
      order.push(id);
      for (let i = node.childIds.length - 1; i >= 0; i--) {
        stack.push({ id: node.childIds[i], depth: depth + 1 });
      }
    }
  };

  if (nodes.has(rootId)) preorder(rootId, 0);
  for (const id of inputOrder) {
    if (!visited.has(id)) preorder(id, 0);
  }
  return order;
}

/**
 * Fill the subtree aggregates in one post-order pass. Requires `order` to be a
 * valid pre-order (so reversing it yields a post-order where children precede
 * parents) and `xSource` to already be set.
 */
export function computeAggregates(nodes: Map<string, MutableNode>, order: readonly string[]): void {
  for (let i = order.length - 1; i >= 0; i--) {
    const node = nodes.get(order[i])!;
    let leaves = 0;
    let count = 1;
    let abundanceSum = node.abundance;
    let maxX = node.xSource;
    for (const childId of node.childIds) {
      const child = nodes.get(childId);
      if (!child) continue;
      leaves += child.subtreeLeafCount;
      count += child.subtreeNodeCount;
      if (abundanceSum !== undefined && child.subtreeAbundanceSum !== undefined) {
        abundanceSum += child.subtreeAbundanceSum;
      } else {
        abundanceSum = undefined;
      }
      if (child.subtreeMaxX > maxX) maxX = child.subtreeMaxX;
    }
    // A node with no children is a terminal slot regardless of the isLeaf flag.
    if (node.childIds.length === 0) leaves = 1;
    node.subtreeLeafCount = leaves;
    node.subtreeNodeCount = count;
    node.subtreeAbundanceSum = abundanceSum;
    node.subtreeMaxX = maxX;
  }
}
