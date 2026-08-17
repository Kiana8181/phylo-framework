from __future__ import annotations

import json
from functools import lru_cache

from apps.api.config import CONTRACTS_DIR
from apps.api.preprocess.method_capabilities import MethodId

# Column requirements are declared in the contracts as the single source of
# truth: packages/contracts/methods/<method>/columns.json. Both this API
# preprocess step and the web docs (apps/web/features/docs/compatibility.ts)
# read those files, so the two cannot drift. See a columns.json for the
# requiredGroups / conditionalGroups shape.
#
# Only the column-mapping methods (dowser, clonaltree, gctree) declare a
# columns.json here; BrepPhylo is not a column-mapping method (it names its
# input columns via flat *_column params) so it has no AIRR column_map
# requirements at this stage.


@lru_cache(maxsize=None)
def _columns_spec(method_id: str) -> dict:
    path = CONTRACTS_DIR / "methods" / method_id / "columns.json"
    if not path.exists():
        return {"requiredGroups": [], "conditionalGroups": []}
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    data.setdefault("requiredGroups", [])
    data.setdefault("conditionalGroups", [])
    return data


def _required_group(method_id: str, group_id: str) -> list[str]:
    for group in _columns_spec(method_id)["requiredGroups"]:
        if group.get("id") == group_id:
            return list(group.get("columns", []))
    return []


def _conditional_group(method_id: str, group_id: str) -> list[str]:
    for group in _columns_spec(method_id)["conditionalGroups"]:
        if group.get("id") == group_id:
            return list(group.get("columns", []))
    return []


def _flat_required(method_id: str) -> list[str]:
    return [c for group in _columns_spec(method_id)["requiredGroups"] for c in group.get("columns", [])]


# Dowser requirements (from packages/contracts/methods/dowser/columns.json).
DOWSER_REQUIRED_KEYS = _flat_required("dowser")
DOWSER_HL_REQUIRED_KEYS = _conditional_group("dowser", "paired_chain")
DOWSER_REGION_REQUIRED_KEYS = _conditional_group("dowser", "regions")

# ClonalTree requirements (from packages/contracts/methods/clonaltree/columns.json).
CLONALTREE_BASE_REQUIRED_KEYS = _required_group("clonaltree", "base")
# Required only when services/clonaltree/app.py runs refinement.py.
CLONALTREE_REFINEMENT_REQUIRED_KEYS = _conditional_group("clonaltree", "refinement")
# Required by alignment_intraclonal.py when ClonalTree builds per-clone trees.
CLONALTREE_ALIGNMENT_REQUIRED_KEYS = _conditional_group("clonaltree", "alignment")
# Required when the existing input alignment is used directly.
CLONALTREE_PREALIGNED_GERMLINE_REQUIRED_KEYS = _conditional_group(
    "clonaltree", "prealigned_germline"
)

CLONALTREE_REQUIRED_KEYS = (
    CLONALTREE_BASE_REQUIRED_KEYS
)

# GCtree tabular adapter requirements only (CSV/TSV -> aligned FASTA path).
GCTREE_TABULAR_REQUIRED_KEYS = _flat_required("gctree")


REQUIRED_KEYS_BY_METHOD: dict[MethodId, list[str]] = {
    "dowser": DOWSER_REQUIRED_KEYS,
    "brepphylo": [],
    "clonaltree": CLONALTREE_REQUIRED_KEYS,
    "gctree": GCTREE_TABULAR_REQUIRED_KEYS,
}


OPTIONAL_KEYS_BY_METHOD: dict[MethodId, list[str]] = {
    "dowser": [],
    "brepphylo": [],
    "clonaltree": [],
    "gctree": [],
}
