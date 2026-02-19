from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


DATA_URL_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.+)$", re.IGNORECASE | re.DOTALL)


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


def _extract_service_image(method_id: str, raw_result: dict[str, Any], idx: int) -> dict[str, str] | None:
    viz = raw_result.get("visualizations")
    if isinstance(viz, dict):
        service_image = viz.get("service_image")
        if isinstance(service_image, dict):
            mime = str(service_image.get("mime") or "").strip()
            base64 = str(service_image.get("base64") or "").strip()
            if mime and base64:
                return {"mime": mime, "base64": base64}

    figures = raw_result.get("figures")
    if not isinstance(figures, dict):
        return None

    method = (method_id or "").strip().lower()
    if method == "gctree":
        # GCtree can emit non-tree charts; never treat those as per-tree service images.
        candidate_keys = ["phylogeny"]
    else:
        candidate_keys = ["phylogeny"] + [k for k in figures.keys() if k != "phylogeny"]
    for key in candidate_keys:
        arr = figures.get(key)
        if not isinstance(arr, list) or idx >= len(arr):
            continue
        raw = arr[idx]
        if raw is None:
            continue
        txt = str(raw).strip()
        if not txt:
            continue
        m = DATA_URL_RE.match(txt)
        if m:
            return {"mime": m.group("mime"), "base64": m.group("data")}
        return {"mime": "image/png", "base64": txt}
    return None


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
    if not isinstance(raw_trees, list):
        raw_trees = []

    warnings_out: list[str | dict[str, Any]] = []
    for w in raw_result.get("warnings") or []:
        warnings_out.append(_normalize_service_warning(w))

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
            tree_obj = {
                "id": tree_id,
                "newick": normalized_newick,
                "original_newick": source_newick,
                "has_lineage_plot": False,
                "has_service_image": False,
            }
            service_image = _extract_service_image(method_id, raw_result, idx)
            tree_obj["has_service_image"] = bool(service_image)
            trees_out.append(tree_obj)
            rows_for_db.append(
                {
                    "tree_index": idx,
                    "tree_id": tree_id,
                    "newick": normalized_newick,
                    "original_newick": source_newick,
                    "service_image": service_image,
                    "node_attributes": None,
                    "lineage_plot": None,
                    "label_to_sequence_id": None,
                }
            )
            continue

        service_image = _extract_service_image(method_id, raw_result, idx)
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
            "newick": normalized_newick,
            "original_newick": source_newick,
            "has_lineage_plot": lineage_plot is not None,
            "has_service_image": bool(service_image),
        }

        trees_out.append(tree_obj)
        rows_for_db.append(
            {
                "tree_index": idx,
                "tree_id": tree_id,
                "newick": normalized_newick,
                "original_newick": source_newick,
                "service_image": service_image,
                "node_attributes": node_attributes if node_attributes else None,
                "lineage_plot": lineage_plot,
                "label_to_sequence_id": label_to_sequence_id if label_to_sequence_id else None,
            }
        )

    unified = dict(raw_result)
    unified["trees"] = trees_out
    unified["warnings"] = warnings_out
    return unified, rows_for_db
