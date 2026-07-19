import type { TreeNodeAttrs } from "@phylo/contracts";
import { parseNewick, type NewickNode } from "@/lib/newick";
import type { LayoutWarning, PhyloAnnotation, TreeModel } from "./types";
import { toAbundance } from "./math";
import { assignOrderAndDepth, computeAggregates, type MutableNode } from "./model";
import { buildAnnoLookup, resolveAnno } from "./phyloDisplay";

/** Ported verbatim from TreeSVG. Strips R print prefix/suffix, ensures `;`. */
export function sanitizeNewick(s: string): string {
  let x = s.trim();
  x = x.replace(/^\[\d+\]\s*"/, "");
  x = x.replace(/"\s*$/, "");
  if (!x.endsWith(";")) x += ";";
  return x;
}

export type FromNewickOptions = {
  annotations?: readonly PhyloAnnotation[];
  /** Numeric annotation field used to derive node abundance (drives radius). */
  sizeByField?: string | null;
};

/**
 * Adapt a Newick string (+ annotations) into a `TreeModel`.
 *
 * - `xSource` = cumulative root-to-node branch length (root = 0). If the tree
 *   has no branch lengths at all, fall back to `depth` so it still spreads
 *   horizontally. (Note: the original TreeSVG left every node at x≈0 in the
 *   no-branch-length case — a degenerate layout. The spec's stated intent is
 *   the depth fallback, which we implement here.)
 * - `ySourceOrder = null` — sibling order is Newick input order.
 * - Annotations are mapped onto nodes by name via the existing lookup logic.
 */
export function fromNewick(newick: string, options: FromNewickOptions = {}): TreeModel {
  const warnings: LayoutWarning[] = [];
  const annoByLabel = buildAnnoLookup(options.annotations);
  const sizeField = options.sizeByField ?? null;

  let root: NewickNode;
  try {
    root = parseNewick(sanitizeNewick(newick));
  } catch {
    warnings.push({ code: "invalid-newick", message: "Failed to parse Newick string." });
    return { rootId: "", nodes: new Map(), order: [], warnings };
  }

  const nodes = new Map<string, MutableNode>();
  const inputOrder: string[] = [];
  const lengthById = new Map<string, number>();
  let counter = 0;
  let sawLength = false;

  const walk = (nnode: NewickNode, parentId: string | null): string => {
    const id = `n${counter++}`;
    inputOrder.push(id);
    const name = (nnode.name ?? "").trim();
    const anno = name ? resolveAnno(annoByLabel, name) : undefined;
    const isLeaf = !nnode.children || nnode.children.length === 0;
    const len =
      typeof nnode.length === "number" && Number.isFinite(nnode.length) ? nnode.length : 0;
    if (parentId !== null && len !== 0) sawLength = true;
    lengthById.set(id, len);

    const sizeVal = sizeField ? anno?.[sizeField] : undefined;
    const abundance = toAbundance(sizeVal ?? anno?.abundance, 1);

    nodes.set(id, {
      id,
      label: name,
      parentId,
      childIds: [],
      isLeaf,
      depth: 0,
      xSource: 0,
      ySourceOrder: null,
      abundance,
      // PhyloAnnotation is a looser record than TreeNodeAttrs; narrow at the
      // adapter boundary (both are string-keyed attribute bags).
      attrs: anno as unknown as TreeNodeAttrs | undefined,
      subtreeLeafCount: 0,
      subtreeNodeCount: 0,
      subtreeAbundanceSum: 0,
      subtreeMaxX: 0,
    });

    const childIds: string[] = [];
    for (const child of nnode.children ?? []) childIds.push(walk(child, id));
    nodes.get(id)!.childIds = childIds;
    return id;
  };

  const rootId = walk(root, null);
  const order = assignOrderAndDepth(nodes, rootId, inputOrder);

  // Cumulative branch length (pre-order guarantees parent precedes child).
  for (const id of order) {
    const node = nodes.get(id)!;
    if (!sawLength) {
      node.xSource = node.depth;
    } else if (node.parentId === null) {
      node.xSource = 0;
    } else {
      const parent = nodes.get(node.parentId);
      node.xSource = (parent?.xSource ?? 0) + (lengthById.get(id) ?? 0);
    }
  }

  computeAggregates(nodes, order);
  return { rootId, nodes, order, warnings };
}
