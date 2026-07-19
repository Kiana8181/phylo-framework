from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# Keys that are NOT persisted in runs.result. Two groups:
#   1. base64 / data-URL payloads → moved to RunArtifact object storage and
#      streamed lazily via the /artifacts API.
#   2. per-tree heavyweight fields → mirrored into run_trees rows and served
#      lazily via /runs/{id}/trees and /runs/{id}/trees/{tree_id}. Keeping a
#      duplicate in runs.result bloats the JSON for runs with many trees.
_STRIPPED_RESULT_KEYS = (
    # base64 / binary
    "figures",
    "artifact_zip_b64",
    "artifact_name",
    "visualizations",
    "render",
    # The artifact manifest is represented by run_artifacts rows + the
    # /runs/{id}/artifacts endpoint; keep it out of the stored result JSON.
    "manifest_version",
    "artifacts",
    # per-tree heavyweight payloads (now sourced via /runs/{id}/trees/{tree_id})
    "node_attributes",
    "node_abundances",
    "annotations",
    "trees_detail",
    "label_to_sequence_id",
    # Raw method `trees` array (Newick + per-tree dicts). We re-emit a slim
    # `unified["trees"]` with just {id, has_lineage_plot}; full newick lives in
    # run_trees and is fetched on demand by the carousel.
    "trees",
)


def _aggregate_dta_switches(switches: Any) -> list[dict[str, Any]]:
    """Collapse the per-clone × per-permutation `switches` rows into a small
    summary table.

    Dowser's discrete_trait_analysis emits one row per (CLONE, FROM, TO, REP)
    tuple. For a moderate run this is ~1M rows / ~110 MB of mostly-zero counts
    that the UI never displays raw — it only shows totals per (FROM, TO).
    We aggregate the observed reconstruction (TYPE == 'RECON', REP == 1)
    summing SWITCHES across clones; the permuted draws (REP > 1) are used
    for the null distribution and don't need to live in the run result JSON.
    """
    if not isinstance(switches, list):
        return []
    totals: dict[tuple[str, str], int] = {}
    for row in switches:
        if not isinstance(row, dict):
            continue
        rep = row.get("REP")
        if rep is not None and rep != 1:
            continue
        row_type = row.get("TYPE")
        if row_type is not None and str(row_type).upper() != "RECON":
            continue
        frm = str(row.get("FROM") or row.get("from") or "").strip()
        to = str(row.get("TO") or row.get("to") or "").strip()
        if not frm or not to:
            continue
        n_raw = row.get("SWITCHES")
        if n_raw is None:
            n_raw = row.get("N") or row.get("count")
        try:
            n_val = int(float(n_raw)) if n_raw is not None else 0
        except (TypeError, ValueError):
            n_val = 0
        key = (frm, to)
        totals[key] = totals.get(key, 0) + n_val
    return [
        {"FROM": frm, "TO": to, "SWITCHES": cnt}
        for (frm, to), cnt in sorted(totals.items(), key=lambda x: (-x[1], x[0]))
    ]


def _slim_dowser_dta(dta: Any) -> Any:
    """Slim the discrete_trait_analysis block before persisting it.

    Drops the unused `raw` arrays under ps/sp/sc (only `summary` is rendered),
    and aggregates the per-permutation `switches` table (typically the
    overwhelming majority of the result JSON for Dowser DTA runs).
    """
    if not isinstance(dta, dict):
        return dta
    slim = dict(dta)
    if "switches" in slim:
        slim["switches"] = _aggregate_dta_switches(slim["switches"])
    for key in ("ps", "sp", "sc"):
        block = slim.get(key)
        if isinstance(block, dict) and "raw" in block:
            block_slim = {k: v for k, v in block.items() if k != "raw"}
            slim[key] = block_slim
    return slim


def _lightweight_result(raw_result: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the method result with binary + per-tree payloads removed.

    Keeps the structured scientific summary (clones, stats, QC, analysis, etc.).
    Defensively drops any remaining ``*_b64`` keys and inline ``data:...;base64``
    string values so no base64 can leak into the stored result JSON. Also slims
    the Dowser DTA block whose raw per-permutation rows can run into the
    hundreds of MB but aren't surfaced as raw in the UI.
    """
    out: dict[str, Any] = {}
    for key, value in raw_result.items():
        if key in _STRIPPED_RESULT_KEYS:
            continue
        if isinstance(key, str) and key.endswith("_b64"):
            continue
        if isinstance(value, str) and value.startswith("data:") and ";base64," in value[:64]:
            continue
        if key == "discrete_trait_analysis":
            value = _slim_dowser_dta(value)
        out[key] = value
    return out


@dataclass
class ParsedNode:
    source_label: str = ""
    norm_label: str = ""
    length: str | None = None
    children: list["ParsedNode"] = field(default_factory=list)
    parent: "ParsedNode | None" = None

    @property
    def is_leaf(self) -> bool:
        return len(self.children) == 0


class _NewickParser:
    def __init__(self, raw: str):
        self.s = raw
        self.i = 0

    def parse(self) -> ParsedNode:
        node = self._parse_subtree()
        self._skip_ws()
        if self.i < len(self.s) and self.s[self.i] == ";":
            self.i += 1
        self._skip_ws()
        if self.i < len(self.s):
            raise ValueError(f"Unexpected trailing Newick content near index {self.i}")
        return node

    def _skip_ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i].isspace():
            self.i += 1

    def _parse_subtree(self) -> ParsedNode:
        self._skip_ws()
        node = ParsedNode()
        if self.i < len(self.s) and self.s[self.i] == "(":
            self.i += 1
            while True:
                child = self._parse_subtree()
                child.parent = node
                node.children.append(child)
                self._skip_ws()
                if self.i >= len(self.s):
                    raise ValueError("Unexpected end of Newick in child list")
                ch = self.s[self.i]
                if ch == ",":
                    self.i += 1
                    continue
                if ch == ")":
                    self.i += 1
                    break
                raise ValueError(f"Unexpected character '{ch}' in Newick child list")
        node.source_label = self._parse_label()
        self._skip_ws()
        if self.i < len(self.s) and self.s[self.i] == ":":
            self.i += 1
            node.length = self._parse_until({",", ")", ";"}).strip() or None
        self._skip_ws()
        return node

    def _parse_label(self) -> str:
        self._skip_ws()
        if self.i >= len(self.s):
            return ""
        ch = self.s[self.i]
        if ch in ",);:":
            return ""
        if ch in ("'", '"'):
            quote = ch
            self.i += 1
            out: list[str] = []
            while self.i < len(self.s):
                cur = self.s[self.i]
                if cur == quote:
                    nxt = self.s[self.i + 1] if self.i + 1 < len(self.s) else ""
                    if nxt == quote:
                        out.append(quote)
                        self.i += 2
                        continue
                    self.i += 1
                    break
                out.append(cur)
                self.i += 1
            return "".join(out).strip()
        return self._parse_until({":", ",", ")", ";"}).strip()

    def _parse_until(self, delimiters: set[str]) -> str:
        out: list[str] = []
        while self.i < len(self.s) and self.s[self.i] not in delimiters:
            out.append(self.s[self.i])
            self.i += 1
        return "".join(out)


def _encode_newick_label(label: str) -> str:
    if not label:
        return ""
    if re.search(r"[\s,:();'\"]", label):
        escaped = label.replace("'", "''")
        return f"'{escaped}'"
    return label


def _ensure_terminal_semicolon(raw_newick: str) -> str:
    x = (raw_newick or "").strip()
    x = re.sub(r'^\[\d+\]\s*"', "", x)
    x = re.sub(r'"\s*$', "", x)
    if x and not x.endswith(";"):
        x += ";"
    return x


def _preorder(root: ParsedNode) -> list[ParsedNode]:
    out: list[ParsedNode] = []

    def walk(node: ParsedNode) -> None:
        out.append(node)
        for child in node.children:
            walk(child)

    walk(root)
    return out


def _unique_label(candidate: str, used: dict[str, int]) -> str:
    base = candidate or "N"
    if base not in used:
        used[base] = 1
        return base
    used[base] += 1
    return f"{base}_{used[base]}"


def _normalize_labels(root: ParsedNode) -> dict[str, list[str]]:
    used: dict[str, int] = {}
    internal_idx = 1
    leaf_idx = 1
    label_aliases: dict[str, list[str]] = {}

    for node in _preorder(root):
        src = (node.source_label or "").strip()
        if src:
            candidate = src
        elif node.is_leaf:
            candidate = f"L{leaf_idx}"
            leaf_idx += 1
        else:
            candidate = f"I{internal_idx}"
            internal_idx += 1
        norm = _unique_label(candidate, used)
        node.norm_label = norm
        if src:
            label_aliases.setdefault(src, []).append(norm)

    return label_aliases


def _serialize_newick(root: ParsedNode) -> str:
    def walk(node: ParsedNode) -> str:
        label = _encode_newick_label(node.norm_label)
        branch = f":{node.length}" if node.length else ""
        if node.children:
            children_txt = ",".join(walk(c) for c in node.children)
            return f"({children_txt}){label}{branch}"
        return f"{label}{branch}"

    return f"{walk(root)};"


def _to_number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        out = float(value)
    except Exception:
        return None
    if out < 0:
        return None
    return out


def _normalize_annotation_rows(annotations: Any) -> list[dict[str, Any]]:
    if not isinstance(annotations, list):
        return []
    out: list[dict[str, Any]] = []
    for row in annotations:
        if isinstance(row, dict):
            out.append(row)
    return out


def _assignment_lookup(label_aliases: dict[str, list[str]]) -> tuple[dict[str, int], dict[str, int]]:
    per_key_cursor = {k: 0 for k in label_aliases}
    direct_cursor = {k: 0 for k in label_aliases}
    return per_key_cursor, direct_cursor


def _resolve_label(
    raw_label: str,
    label_aliases: dict[str, list[str]],
    per_key_cursor: dict[str, int],
) -> str | None:
    if raw_label in label_aliases:
        seq = label_aliases[raw_label]
        idx = per_key_cursor.get(raw_label, 0)
        if idx < len(seq):
            per_key_cursor[raw_label] = idx + 1
            return seq[idx]
    return None


def _index_nodes(root: ParsedNode) -> tuple[dict[str, ParsedNode], list[ParsedNode]]:
    nodes = _preorder(root)
    by_label = {n.norm_label: n for n in nodes}
    return by_label, nodes


def _extract_tree_specific_map(raw_result: dict[str, Any], key: str, idx: int) -> dict[str, Any]:
    value = raw_result.get(key)
    if isinstance(value, list):
        if idx < len(value) and isinstance(value[idx], dict):
            return dict(value[idx])
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _derive_leaf_abundance_from_rows(rows: list[dict[str, Any]]) -> int:
    dup_values = [_to_number(r.get("duplicate_count")) for r in rows]
    dup_sum = sum(v for v in dup_values if v is not None)
    if dup_sum > 0:
        return max(1, int(round(dup_sum)))

    umi_values = [_to_number(r.get("umi_count")) for r in rows]
    umi_sum = sum(v for v in umi_values if v is not None)
    if umi_sum > 0:
        return max(1, int(round(umi_sum)))

    if rows:
        return max(1, len(rows))
    return 1


def _build_lineage_layout(
    root: ParsedNode,
    node_attributes: dict[str, dict[str, Any]],
    normalized_newick: str,
) -> dict[str, Any]:
    by_label, nodes = _index_nodes(root)
    if not nodes:
        raise ValueError("No nodes found in normalized Newick")

    x_spacing = 180.0
    y_spacing = 62.0
    margin = 36.0

    depth_by_label: dict[str, int] = {}

    def mark_depth(node: ParsedNode, depth: int) -> None:
        depth_by_label[node.norm_label] = depth
        for child in node.children:
            mark_depth(child, depth + 1)

    mark_depth(root, 0)
    max_depth = max(depth_by_label.values()) if depth_by_label else 0

    leaves = [n for n in nodes if n.is_leaf]
    y_by_label: dict[str, float] = {}
    for i, leaf in enumerate(leaves):
        y_by_label[leaf.norm_label] = margin + y_spacing * i

    def place_internal(node: ParsedNode) -> float:
        if node.is_leaf:
            return y_by_label[node.norm_label]
        child_ys = [place_internal(c) for c in node.children]
        y = sum(child_ys) / max(1, len(child_ys))
        y_by_label[node.norm_label] = y
        return y

    place_internal(root)

    nodes_out: list[dict[str, Any]] = []
    edges_out: list[dict[str, str]] = []
    for node in nodes:
        depth = depth_by_label[node.norm_label]
        x = margin + depth * x_spacing
        y = y_by_label[node.norm_label]
        parent_id = node.parent.norm_label if node.parent is not None else None
        attrs = node_attributes.get(node.norm_label, {})
        abundance = _to_number(attrs.get("abundance"))
        node_obj = {
            "id": node.norm_label,
            "label": node.norm_label,
            "x": x,
            "y": y,
            "isLeaf": node.is_leaf,
        }
        if parent_id:
            node_obj["parentId"] = parent_id
            edges_out.append({"source": parent_id, "target": node.norm_label})
        if abundance is not None and abundance >= 1:
            node_obj["abundance"] = abundance
        nodes_out.append(node_obj)

    width = margin * 2 + max_depth * x_spacing
    height = margin * 2 + max(0, len(leaves) - 1) * y_spacing

    return {
        "format": "lineage-plot-v1",
        "nodes": nodes_out,
        "edges": edges_out,
        "meta": {
            "rootId": root.norm_label,
            "germlineLabel": "germline",
            "width": width,
            "height": height,
            "normalizedNewick": normalized_newick,
        },
    }


def _merge_dowser_lineage_metadata(
    lineage_plot: dict[str, Any] | None,
    node_attributes: dict[str, dict[str, Any]],
    trees_detail_nodes: list[dict[str, Any]] | None,
) -> None:
    if not lineage_plot or not trees_detail_nodes:
        return

    by_id: dict[str, dict[str, Any]] = {}
    internals: list[dict[str, Any]] = []
    for nd in trees_detail_nodes:
        if not isinstance(nd, dict):
            continue
        node_id = str(nd.get("node_id") or "").strip()
        if node_id:
            by_id[node_id] = nd
        if nd.get("is_internal"):
            internals.append(nd)

    internals.sort(key=lambda x: int(x.get("node") or 0))
    internal_idx = 0

    for plot_node in lineage_plot.get("nodes") or []:
        if not isinstance(plot_node, dict):
            continue
        label = str(plot_node.get("label") or plot_node.get("id") or "").strip()
        is_leaf = bool(plot_node.get("isLeaf"))
        dowser_nd: dict[str, Any] | None = by_id.get(label)

        if not dowser_nd and not is_leaf and internal_idx < len(internals):
            dowser_nd = internals[internal_idx]
            internal_idx += 1

        if not dowser_nd:
            continue

        merged = {
            "isInternal": bool(dowser_nd.get("is_internal")),
            "nodeNumber": dowser_nd.get("node"),
            "node_id": dowser_nd.get("node_id"),
            "sequence": dowser_nd.get("sequence"),
            "sequence_alignment": dowser_nd.get("sequence_alignment"),
            "locus": dowser_nd.get("locus"),
        }
        merged = {k: v for k, v in merged.items() if v is not None and v != ""}

        attrs = node_attributes.setdefault(label, {})
        attrs.update(merged)
        plot_node.update(merged)


def _normalize_service_warning(w: Any) -> str | dict[str, Any]:
    if isinstance(w, str):
        return w
    if isinstance(w, dict):
        code = str(w.get("code") or "").strip()
        msg = str(w.get("message") or "").strip()
        if code and msg:
            return w
    return str(w)


def _build_node_attributes(
    *,
    method_id: str,
    root: ParsedNode,
    idx: int,
    raw_result: dict[str, Any],
    label_aliases: dict[str, list[str]],
) -> tuple[dict[str, dict[str, Any]], dict[str, str]]:
    nodes_by_label, nodes = _index_nodes(root)
    node_attributes: dict[str, dict[str, Any]] = {label: {} for label in nodes_by_label}
    label_to_sequence_id: dict[str, str] = {}
    label_cursor, _ = _assignment_lookup(label_aliases)

    # 1) existing node_attributes from service (if present)
    provided_attrs = _extract_tree_specific_map(raw_result, "node_attributes", idx)
    for raw_label, attrs in provided_attrs.items():
        if not isinstance(attrs, dict):
            continue
        target = raw_label if raw_label in nodes_by_label else _resolve_label(str(raw_label), label_aliases, label_cursor)
        if not target or target not in node_attributes:
            continue
        node_attributes[target].update(attrs)
        seq = attrs.get("sequence_id")
        if isinstance(seq, str) and seq.strip():
            label_to_sequence_id[target] = seq.strip()

    # 2) annotation rows (legacy services)
    annos = raw_result.get("annotations")
    rows = _normalize_annotation_rows(annos[idx] if isinstance(annos, list) and idx < len(annos) else None)
    anno_grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        row_label = str(row.get("label") or "").strip()
        if not row_label:
            continue
        target = row_label if row_label in nodes_by_label else _resolve_label(row_label, label_aliases, label_cursor)
        if not target or target not in node_attributes:
            continue
        merged = dict(row)
        merged.pop("label", None)
        node_attributes[target].update(merged)
        anno_grouped.setdefault(target, []).append(row)

        seq = row.get("sequence_id")
        if isinstance(seq, str) and seq.strip():
            label_to_sequence_id[target] = seq.strip()
            node_attributes[target]["sequence_id"] = seq.strip()

    # 3) explicit label_to_sequence_id map
    provided_l2s = _extract_tree_specific_map(raw_result, "label_to_sequence_id", idx)
    for raw_label, seq_id in provided_l2s.items():
        if not isinstance(seq_id, str) or not seq_id.strip():
            continue
        target = raw_label if raw_label in nodes_by_label else _resolve_label(str(raw_label), label_aliases, label_cursor)
        if not target or target not in node_attributes:
            continue
        label_to_sequence_id[target] = seq_id.strip()
        node_attributes[target]["sequence_id"] = seq_id.strip()

    # 4) abundance handling
    provided_abundances_raw = _extract_tree_specific_map(raw_result, "node_abundances", idx)
    abundance_cursor, _ = _assignment_lookup(label_aliases)
    for raw_label, value in provided_abundances_raw.items():
        abundance = _to_number(value)
        if abundance is None:
            continue
        target = raw_label if raw_label in nodes_by_label else _resolve_label(str(raw_label), label_aliases, abundance_cursor)
        if not target or target not in node_attributes:
            continue
        node_attributes[target]["abundance"] = max(1.0, abundance)

    method = (method_id or "").lower()
    if method in {"dowser", "brepphylo"}:
        for node in nodes:
            if node.is_leaf:
                abundance = _derive_leaf_abundance_from_rows(anno_grouped.get(node.norm_label, []))
                node_attributes[node.norm_label]["abundance"] = max(1, abundance)
            else:
                node_attributes[node.norm_label]["abundance"] = 1
    else:
        for node in nodes:
            existing_abund = _to_number(node_attributes[node.norm_label].get("abundance"))
            if existing_abund is None:
                node_attributes[node.norm_label]["abundance"] = 1
            else:
                node_attributes[node.norm_label]["abundance"] = max(1.0, existing_abund)

    return node_attributes, label_to_sequence_id


def _normalize_tree_input(tree_item: Any) -> str | None:
    if isinstance(tree_item, str):
        x = _ensure_terminal_semicolon(tree_item)
        return x or None
    if isinstance(tree_item, dict):
        for key in ("original_newick", "newick"):
            v = tree_item.get(key)
            if isinstance(v, str) and v.strip():
                return _ensure_terminal_semicolon(v)
    return None


def assemble_unified_tree_result(
    method_id: str,
    raw_result: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if not isinstance(raw_result, dict):
        return {"ok": False}, []

    raw_trees = raw_result.get("trees")
    # Some method services (notably R/plumber with auto_unbox) may emit a
    # single tree as a scalar string instead of a JSON array.
    if isinstance(raw_trees, list):
        pass
    elif raw_trees is None:
        raw_trees = []
    else:
        raw_trees = [raw_trees]

    warnings_out: list[str | dict[str, Any]] = []
    for w in raw_result.get("warnings") or []:
        warnings_out.append(_normalize_service_warning(w))

    # gctree emits a download-only `display_newick` list aligned 1:1 with `trees`
    # (original sequence_ids as labels). Passed through untouched and stored per
    # tree; other methods omit it. No relabeling happens in this layer.
    raw_display_newick = raw_result.get("display_newick")

    def _display_newick_for(idx: int) -> str | None:
        if not isinstance(raw_display_newick, list) or idx >= len(raw_display_newick):
            return None
        value = raw_display_newick[idx]
        return value if isinstance(value, str) and value.strip() else None

    trees_out: list[dict[str, Any]] = []
    rows_for_db: list[dict[str, Any]] = []

    for idx, raw_tree in enumerate(raw_trees):
        source_newick = _normalize_tree_input(raw_tree)
        if not source_newick:
            continue

        tree_id = f"{method_id}-tree-{idx + 1}"
        try:
            parsed = _NewickParser(source_newick).parse()
            label_aliases = _normalize_labels(parsed)
            normalized_newick = _serialize_newick(parsed)
        except Exception as exc:
            warnings_out.append(
                {
                    "code": "NEWICK_PARSE_FAILED",
                    "message": "Failed to parse Newick; lineage layout cannot be generated for this tree.",
                    "treeId": tree_id,
                    "details": {"reason": str(exc)},
                }
            )
            normalized_newick = _ensure_terminal_semicolon(source_newick)
            # Slim per-tree summary only; newick stays in run_trees and is
            # served by /runs/{id}/trees/{tree_id}.
            tree_obj = {
                "id": tree_id,
                "has_lineage_plot": False,
            }
            trees_out.append(tree_obj)
            rows_for_db.append(
                {
                    "tree_index": idx,
                    "tree_id": tree_id,
                    "newick": normalized_newick,
                    "original_newick": source_newick,
                    "node_attributes": None,
                    "lineage_plot": None,
                    "label_to_sequence_id": None,
                    "display_newick": _display_newick_for(idx),
                }
            )
            continue

        node_attributes, label_to_sequence_id = _build_node_attributes(
            method_id=method_id,
            root=parsed,
            idx=idx,
            raw_result=raw_result,
            label_aliases=label_aliases,
        )

        lineage_plot: dict[str, Any] | None = None
        try:
            lineage_plot = _build_lineage_layout(parsed, node_attributes, normalized_newick)
            if (method_id or "").lower() == "dowser":
                trees_detail = raw_result.get("trees_detail")
                detail_nodes: list[dict[str, Any]] | None = None
                if isinstance(trees_detail, list) and idx < len(trees_detail):
                    detail_item = trees_detail[idx]
                    if isinstance(detail_item, dict):
                        nodes_raw = detail_item.get("nodes")
                        if isinstance(nodes_raw, list):
                            detail_nodes = [n for n in nodes_raw if isinstance(n, dict)]
                _merge_dowser_lineage_metadata(lineage_plot, node_attributes, detail_nodes)
        except Exception as exc:
            warnings_out.append(
                {
                    "code": "LINEAGE_PLOT_FAILED",
                    "message": "Failed to generate lineage layout for this tree; phylogeny remains available.",
                    "treeId": tree_id,
                    "details": {"reason": str(exc)},
                }
            )

        tree_obj: dict[str, Any] = {
            "id": tree_id,
            "has_lineage_plot": lineage_plot is not None,
        }

        trees_out.append(tree_obj)
        rows_for_db.append(
            {
                "tree_index": idx,
                "tree_id": tree_id,
                "newick": normalized_newick,
                "original_newick": source_newick,
                "node_attributes": node_attributes if node_attributes else None,
                "lineage_plot": lineage_plot,
                "label_to_sequence_id": label_to_sequence_id if label_to_sequence_id else None,
                "display_newick": _display_newick_for(idx),
            }
        )

    unified = _lightweight_result(raw_result)
    unified["trees"] = trees_out
    unified["warnings"] = warnings_out
    return unified, rows_for_db
