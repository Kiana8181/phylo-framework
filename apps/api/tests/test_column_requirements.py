"""Locks the column-requirement values (now sourced from the contracts
columns.json) and the gate-combination behaviour of active_required_keys.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_column_requirements.py
"""
from pathlib import Path

from apps.api.preprocess.column_requirements import (
    CLONALTREE_ALIGNMENT_REQUIRED_KEYS,
    CLONALTREE_BASE_REQUIRED_KEYS,
    CLONALTREE_PREALIGNED_GERMLINE_REQUIRED_KEYS,
    CLONALTREE_REFINEMENT_REQUIRED_KEYS,
    DOWSER_HL_REQUIRED_KEYS,
    DOWSER_REGION_REQUIRED_KEYS,
    DOWSER_REQUIRED_KEYS,
    GCTREE_TABULAR_REQUIRED_KEYS,
    REQUIRED_KEYS_BY_METHOD,
)
from apps.api.preprocess.prepare_input import active_required_keys
from apps.api.preprocess.prepare_input import prepare_input_for_method


def test_dowser_constants_match_contract():
    assert DOWSER_REQUIRED_KEYS == [
        "sequence_id",
        "clone_id",
        "sequence_alignment",
        "germline_alignment_d_mask",
        "v_call",
        "j_call",
        "junction_length",
    ]
    assert DOWSER_HL_REQUIRED_KEYS == ["cell_id", "locus"]
    assert DOWSER_REGION_REQUIRED_KEYS == [
        "v_region_start",
        "v_region_end",
        "j_region_start",
        "j_region_end",
    ]


def test_gctree_and_brepphylo():
    assert GCTREE_TABULAR_REQUIRED_KEYS == ["sequence_id", "sequence_alignment"]
    # BrepPhylo is not a column-mapping method — no AIRR column_map requirements.
    assert REQUIRED_KEYS_BY_METHOD["brepphylo"] == []


def test_active_required_keys_dowser_gates():
    base = set(DOWSER_REQUIRED_KEYS)
    assert set(active_required_keys("dowser", {})) == base
    assert set(active_required_keys("dowser", {"chain_mode": "HL"})) == base | {"cell_id", "locus"}
    assert set(active_required_keys("dowser", {"use_regions": True})) == base | set(
        DOWSER_REGION_REQUIRED_KEYS
    )


def test_active_required_keys_clonaltree_refinement_default_on():
    always = set(CLONALTREE_BASE_REQUIRED_KEYS)
    refinement = set(CLONALTREE_REFINEMENT_REQUIRED_KEYS)
    # Refinement is on by default (absent use_refinement -> True).
    alignment = set(CLONALTREE_ALIGNMENT_REQUIRED_KEYS)
    assert set(active_required_keys("clonaltree", {})) == always | refinement | alignment
    assert set(active_required_keys("clonaltree", {"use_refinement": True})) == always | refinement | alignment
    # Explicitly disabled -> refinement columns drop out.
    assert set(active_required_keys("clonaltree", {"use_refinement": False})) == always | alignment
    # Pre-aligned mode replaces the generated alignment requirements with its
    # germline-root input.
    prealigned = {"use_input_alignment": True, "use_refinement": False}
    assert set(active_required_keys("clonaltree", prealigned)) == (
        always | set(CLONALTREE_PREALIGNED_GERMLINE_REQUIRED_KEYS)
    )


def test_clonaltree_prealigned_mapping_accepts_minimal_input(tmp_path: Path):
    source = tmp_path / "input.tsv"
    source.write_text(
        "sid\tprod\tvcall\tdcall\tjcall\tseqal\tjuncaa\tcdr3aa\tgerm\n"
        "s1\tT\tV1\tD1\tJ1\tACGT\tAAA\tCCC\tACGT\n",
        encoding="utf-8",
    )

    prepared = prepare_input_for_method(
        "clonaltree",
        source,
        params={
            "doMapping": True,
            "use_input_alignment": True,
            "use_refinement": False,
            "column_map": {
                "sequence_id": "sid",
                "productive": "prod",
                "v_call": "vcall",
                "d_call": "dcall",
                "j_call": "jcall",
                "sequence_alignment": "seqal",
                "junction_aa": "juncaa",
                "cdr3_aa": "cdr3aa",
                "germline_alignment_d_mask": "germ",
            },
        },
        work_dir=tmp_path / "work",
    )

    assert prepared.final_path.read_text(encoding="utf-8").splitlines()[0].split("\t") == [
        "sequence_id",
        "productive",
        "v_call",
        "d_call",
        "j_call",
        "sequence_alignment",
        "junction_aa",
        "cdr3_aa",
        "germline_alignment_d_mask",
    ]
