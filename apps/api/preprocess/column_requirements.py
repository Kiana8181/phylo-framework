from __future__ import annotations

from apps.api.preprocess.method_capabilities import MethodId

# Dowser requirements from services/dowser/plumber.R::validate_airr_for_dowser
DOWSER_REQUIRED_KEYS = [
    "sequence_id",
    "clone_id",
    "sequence_alignment",
    "germline_alignment_d_mask",
    "v_call",
    "j_call",
    "junction",
]

# ClonalTree requirements from base-codes formatter + downstream scripts.
CLONALTREE_BASE_REQUIRED_KEYS = [
    "sequence_id",
    "productive",
    "v_call",
    "d_call",
    "j_call",
    "sequence_alignment",
    "junction_aa",
    "cdr3_aa",
]

# Required only when services/clonaltree/app.py runs refinement.py.
CLONALTREE_REFINEMENT_REQUIRED_KEYS = [
    "j_sequence_alignment",
    "v_sequence_alignment",
    "j_sequence_alignment_aa",
    "v_sequence_alignment_aa",
]

CLONALTREE_REQUIRED_KEYS = CLONALTREE_BASE_REQUIRED_KEYS + CLONALTREE_REFINEMENT_REQUIRED_KEYS

# GCtree tabular adapter requirements only (CSV/TSV -> aligned FASTA path).
GCTREE_TABULAR_REQUIRED_KEYS = [
    "sequence_id",
    "sequence_alignment",
]


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
