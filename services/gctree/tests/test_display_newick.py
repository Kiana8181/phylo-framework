"""Unit tests for gctree's download-only ``display_newick`` relabeling.

``build_display_newick`` rewrites the canonical Newick's node-name tokens with
the user's original sequence_ids (the same ``label_to_sequence_id`` map the
result ships), preserving topology and branch lengths byte-for-byte. It is
download-only and never drives layout.

Run from services/gctree:
    python -m pytest tests/test_display_newick.py
"""
import os
import sys
import tempfile
from pathlib import Path

# app.py instantiates a JobManager at import time which mkdirs the jobs root;
# point it at a writable temp dir so importing the module works off-container.
os.environ.setdefault("METHOD_JOBS_DIR", tempfile.mkdtemp(prefix="gctree-jobs-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import build_display_newick, _escape_newick_label  # noqa: E402

# A realistic gctree forest tree: observed tips + an observed internal node
# (seq5) + an inferred germline root (naive9), with branch lengths.
CANONICAL = "(seq18:2,seq29:1,(seq3:0.5,seq7:1)seq5:3)naive9:0;"


def test_singleton_label_relabels_to_original_id():
    dn, warnings = build_display_newick(CANONICAL, {"seq18": "PatientA_001"})
    assert "PatientA_001:2" in dn
    # Unmapped labels untouched.
    assert "seq29:1" in dn
    assert dn.endswith("naive9:0;")
    assert warnings == []


def test_collapsed_node_uses_representative_and_does_not_inline_set():
    # label_to_sequence_id carries ONE representative per collapsed node; the
    # full member set is never inlined into the label.
    dn, warnings = build_display_newick(CANONICAL, {"seq18": "rep_id"})
    assert "rep_id:2" in dn
    assert ":" not in "rep_id"  # representative is a single token, no set join
    assert warnings == []


def test_special_characters_are_single_quote_quoted():
    dn, _ = build_display_newick(
        CANONICAL,
        {
            "seq29": "clone:42|heavy",  # colon + pipe
            "seq3": "sample 3",  # whitespace
            "seq7": "d'Arcy",  # embedded single quote -> doubled
        },
    )
    assert "'clone:42|heavy':1" in dn
    assert "'sample 3':0.5" in dn
    assert "'d''Arcy':1" in dn


def test_unmapped_labels_pass_through_unchanged():
    # naive9 (germline root) + inferred internals never appear in the map.
    dn, warnings = build_display_newick(CANONICAL, {"seq18": "A"})
    assert "naive9:0;" in dn  # root left unchanged per policy
    assert warnings == []


def test_observed_internal_node_relabels():
    dn, _ = build_display_newick(CANONICAL, {"seq5": "internal_obs_5"})
    assert "internal_obs_5:3" in dn


def test_topology_and_branch_lengths_byte_stable_with_empty_map():
    # No mappings -> output must be byte-identical to the canonical input.
    dn, warnings = build_display_newick(CANONICAL, {})
    assert dn == CANONICAL
    assert warnings == []


def test_topology_and_branch_lengths_byte_stable_when_relabeled():
    # Only the label tokens change; every structural char and branch length
    # is preserved exactly.
    dn, _ = build_display_newick(
        CANONICAL, {"seq18": "A", "seq29": "B", "seq3": "C", "seq7": "D", "seq5": "E"}
    )
    assert dn == "(A:2,B:1,(C:0.5,D:1)E:3)naive9:0;"


def test_forced_collision_keeps_canonical_and_warns():
    canonical = "(a:1,b:2)r;"
    dn, warnings = build_display_newick(canonical, {"a": "X", "b": "X"})
    assert dn == canonical  # both colliding nodes kept canonical labels
    assert len(warnings) == 1
    assert "collide" in warnings[0]


def test_multi_tree_display_is_index_aligned_with_trees():
    # Mirrors the payload loop: one display newick per input tree, same order.
    trees = [CANONICAL, "(seq18:1,naive9:0);"]
    mapping = {"seq18": "A"}
    display = [build_display_newick(t, mapping)[0] for t in trees]
    assert len(display) == len(trees)
    assert display[0].startswith("(A:2,")
    assert display[1] == "(A:1,naive9:0);"


def test_escape_helper_only_quotes_when_needed():
    assert _escape_newick_label("simple_id.1") == "simple_id.1"
    assert _escape_newick_label("a:b") == "'a:b'"
    assert _escape_newick_label("has space") == "'has space'"
    assert _escape_newick_label("it's") == "'it''s'"
