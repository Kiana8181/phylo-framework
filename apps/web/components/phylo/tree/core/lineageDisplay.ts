import type { TreeNodeModel } from "./types";

export type DetailRow = { key: string; value: string };

/**
 * Display-label / rows helpers for the lineage view, ported verbatim
 * from LineageSVG but rebased onto `TreeNodeModel` (attrs live on the node).
 * These are display concerns invoked at render time with the current options.
 */

export function resolveDisplayLabel(
  node: TreeNodeModel,
  displayIdField?: string | null,
): string {
  const attrs = node.attrs;
  if (displayIdField) {
    const selected = String(attrs?.[displayIdField] ?? "").trim();
    if (selected) return selected;
  }
  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq) return seq;
  const label = String(node.label ?? "").trim();
  if (label) return label;
  return node.id;
}

export function resolveNodeDisplayLabel(
  node: TreeNodeModel,
  displayIdField: string | null | undefined,
  showInternalNodes: boolean,
  showNodeNumbers: boolean,
): string {
  const attrs = node.attrs;
  if (!node.isLeaf && showInternalNodes) {
    const nodeId = String(attrs?.node_id ?? "").trim();
    const seq = String(attrs?.sequence ?? "").trim();
    const nodeNum = attrs?.nodeNumber ?? attrs?.node;
    if (showNodeNumbers && nodeNum != null && String(nodeNum).trim()) {
      const numLabel = `#${nodeNum}`;
      if (nodeId) return `${numLabel} ${nodeId}`;
      if (seq) return `${numLabel} ${seq.slice(0, 12)}`;
      return numLabel;
    }
    if (nodeId) return nodeId;
    if (seq) return seq.length > 16 ? `${seq.slice(0, 16)}…` : seq;
  }
  return resolveDisplayLabel(node, displayIdField);
}

/** Structured field rows for the node-detail modal (clicking a node). */
export function buildRows(node: TreeNodeModel): DetailRow[] {
  const attrs = node.attrs;
  const rows: DetailRow[] = [{ key: "label", value: String(node.label ?? node.id) }];
  const seq = String(attrs?.sequence_id ?? "").trim();
  if (seq) rows.push({ key: "sequence_id", value: seq });
  rows.push({ key: "abundance", value: String(node.abundance) });
  if (node.parentId) rows.push({ key: "parentId", value: String(node.parentId) });
  rows.push({ key: "type", value: node.isLeaf ? "leaf" : "internal" });
  if (attrs && typeof attrs === "object") {
    const ignored = new Set<string>(["tooltip", "sequence_id", "abundance"]);
    for (const key of Object.keys(attrs)
      .filter((k) => !ignored.has(k))
      .sort((a, b) => a.localeCompare(b, "en"))) {
      const value = String(attrs[key] ?? "").trim();
      if (value) rows.push({ key, value });
    }
  }
  return rows;
}
