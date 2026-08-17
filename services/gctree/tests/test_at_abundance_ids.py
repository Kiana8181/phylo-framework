"""Unit tests for GCtree's ``name@abundance`` FASTA header handling.

GCtree writes IDs like ``seq3@9`` in its own output but cannot read them back:
``deduplicate`` only treats all-digit IDs as counts, so the abundances are lost,
and the ``@`` survives into the PHYLIP file where DNAPARS rewrites the taxon
name and gctree's later root lookup fails with ``IndexError``.

Run from services/gctree:
    python -m pytest tests/test_at_abundance_ids.py
"""
import os
import sys
import tempfile
from pathlib import Path

import pytest

# app.py instantiates a JobManager at import time which mkdirs the jobs root;
# point it at a writable temp dir so importing the module works off-container.
os.environ.setdefault("METHOD_JOBS_DIR", tempfile.mkdtemp(prefix="gctree-jobs-"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app import (  # noqa: E402
    ID_STYLE_AT_ABUNDANCE,
    ID_STYLE_OTHER_AT,
    ID_STYLE_PLAIN,
    FastaRecord,
    bridge_deduplicate_idmap_to_original,
    build_display_newick,
    classify_fasta_id_style,
    is_gctree_safe_fasta_id,
    normalize_idmap_for_display,
    parse_abundances_csv,
    parse_deduplicate_idmap_members,
    rewrite_abundances_from_at_ids,
    strip_at_abundance_ids,
    validate_gctree_safe_fasta_ids,
)


def rec(sid: str, seq: str = "ACGT") -> FastaRecord:
    return FastaRecord(original_id=sid, sequence=seq)


# ---------- is_gctree_safe_fasta_id ----------


@pytest.mark.parametrize("sid", ["naive", "seq3", "GL", "a_b.c", "S000001", "x" * 10])
def test_safe_ids_accepted(sid):
    assert is_gctree_safe_fasta_id(sid) is True


@pytest.mark.parametrize(
    "sid",
    [
        "naive@0",  # the header form that caused the original crash
        "a-b",
        "x|y",
        "a:b",
        "a b",
        "café",
        "",
        "12345",  # collides with DNAPARS internal node names
        "x" * 11,  # over the PHYLIP limit
    ],
)
def test_unsafe_ids_rejected(sid):
    assert is_gctree_safe_fasta_id(sid) is False


def test_validation_message_names_the_offending_characters():
    err = validate_gctree_safe_fasta_ids([rec("naive@0")])
    assert err is not None
    assert "'@'" in err
    assert "A-Z a-z 0-9 _ ." in err


# ---------- classify_fasta_id_style ----------


def test_style_at_abundance_when_every_id_matches():
    records = [rec("naive@0"), rec("seq3@9"), rec("seq5@4")]
    assert classify_fasta_id_style(records) == ID_STYLE_AT_ABUNDANCE


def test_style_plain_without_any_at():
    assert classify_fasta_id_style([rec("naive"), rec("seq3")]) == ID_STYLE_PLAIN


def test_style_other_at_when_only_some_match():
    records = [rec("naive@0"), rec("seq3")]
    assert classify_fasta_id_style(records) == ID_STYLE_OTHER_AT


def test_style_other_at_when_suffix_is_not_an_integer():
    records = [rec("naive@0"), rec("seq3@IgG")]
    assert classify_fasta_id_style(records) == ID_STYLE_OTHER_AT


def test_style_plain_for_empty_input():
    assert classify_fasta_id_style([]) == ID_STYLE_PLAIN


# ---------- strip_at_abundance_ids ----------


def test_strip_returns_names_and_abundances():
    result = strip_at_abundance_ids([rec("naive@0"), rec("seq3@9", "TTTT")])
    assert [r.original_id for r in result.records] == ["naive", "seq3"]
    assert [r.sequence for r in result.records] == ["ACGT", "TTTT"]
    assert result.abundance_by_original == {"naive@0": 0, "seq3@9": 9}
    assert result.stripped_by_original["seq3@9"] == "seq3"
    assert result.original_by_stripped["seq3"] == "seq3@9"


def test_strip_rejects_names_that_collide_once_the_suffix_is_gone():
    with pytest.raises(ValueError, match="collide"):
        strip_at_abundance_ids([rec("seq1@2"), rec("seq1@3")])


def test_strip_rejects_ids_that_are_not_in_the_at_form():
    with pytest.raises(ValueError, match="does not use"):
        strip_at_abundance_ids([rec("seq1")])


# ---------- parse_deduplicate_idmap_members ----------


def test_members_are_split_on_colons(tmp_path):
    # deduplicate writes 'label,id1:id2'; the root's line has no members at all.
    p = tmp_path / "idmap.txt"
    p.write_text("naive,\nseq1,seq3:seq120\nseq2,seq5\n")
    assert parse_deduplicate_idmap_members(p) == {
        "naive": [],
        "seq1": ["seq3", "seq120"],
        "seq2": ["seq5"],
    }


def test_members_of_a_missing_file_are_empty(tmp_path):
    assert parse_deduplicate_idmap_members(tmp_path / "nope.txt") == {}


# ---------- rewrite_abundances_from_at_ids ----------


@pytest.fixture
def dedup_artifacts(tmp_path):
    """A deduplicate run over naive@0, seq3@9, seq120@1, seq5@4.

    seq3 and seq120 collapsed onto one label; the root label carries no members
    of its own (deduplicate excludes the root record from its own id_map).
    """
    idmap = tmp_path / "idmap.txt"
    idmap.write_text("naive,\nseq1,seq3:seq120\nseq2,seq5\n")

    fasta_idmap = tmp_path / "fasta_idmap.tsv"
    fasta_idmap.write_text(
        "safe_id\toriginal_id\n"
        "naive\tnaive@0\n"
        "seq3\tseq3@9\n"
        "seq120\tseq120@1\n"
        "seq5\tseq5@4\n"
    )

    abund = tmp_path / "abundances.csv"
    abund.write_text("naive,0\nseq1,2\nseq2,1\n")  # deduplicate's own record counts
    return abund, idmap, fasta_idmap


def test_rewrite_replaces_record_counts_with_at_abundances(dedup_artifacts):
    abund, idmap, fasta_idmap = dedup_artifacts
    counts, unmapped = rewrite_abundances_from_at_ids(
        abund, idmap, fasta_idmap, {"naive@0": 0, "seq3@9": 9, "seq120@1": 1, "seq5@4": 4}
    )
    assert unmapped == []
    assert counts == {"naive": 0, "seq1": 10, "seq2": 4}
    # The rewritten file must still parse with the reader gctree infer relies on.
    assert parse_abundances_csv(abund) == {"naive": 0.0, "seq1": 10.0, "seq2": 4.0}


def test_rewrite_keeps_the_label_set_deduplicate_produced(dedup_artifacts):
    abund, idmap, fasta_idmap = dedup_artifacts
    before = set(parse_abundances_csv(abund))
    counts, _ = rewrite_abundances_from_at_ids(
        abund, idmap, fasta_idmap, {"naive@0": 0, "seq3@9": 9, "seq120@1": 1, "seq5@4": 4}
    )
    assert set(counts) == before


def test_rewrite_excludes_the_roots_own_abundance(dedup_artifacts):
    """gctree derives the root's abundance only from sequences identical to it."""
    abund, idmap, fasta_idmap = dedup_artifacts
    counts, _ = rewrite_abundances_from_at_ids(
        abund, idmap, fasta_idmap, {"naive@0": 7, "seq3@9": 9, "seq120@1": 1, "seq5@4": 4}
    )
    assert counts["naive"] == 0


def test_rewrite_reports_members_it_cannot_trace(dedup_artifacts):
    abund, idmap, fasta_idmap = dedup_artifacts
    counts, unmapped = rewrite_abundances_from_at_ids(
        abund, idmap, fasta_idmap, {"naive@0": 0, "seq3@9": 9, "seq5@4": 4}
    )
    assert unmapped == ["seq120"]
    assert counts["seq1"] == 9  # the untraceable member counts as 0


def test_rewrite_rejects_an_empty_idmap(tmp_path):
    with pytest.raises(ValueError, match="idmap is empty"):
        rewrite_abundances_from_at_ids(
            tmp_path / "a.csv", tmp_path / "missing.txt", tmp_path / "m.tsv", {}
        )


# ---------- bridge_deduplicate_idmap_to_original ----------


def test_bridge_maps_every_member_of_a_collapsed_label(dedup_artifacts):
    """Regression: collapsed labels used to leak internal safe IDs to the UI."""
    abund, idmap, fasta_idmap = dedup_artifacts
    out = idmap.parent / "idmap.original.tsv"
    ok, count, unmapped = bridge_deduplicate_idmap_to_original(idmap, fasta_idmap, out)
    assert ok is True
    assert unmapped == []
    assert count == 3
    assert out.read_text().splitlines() == ["seq1\tseq3@9|seq120@1", "seq2\tseq5@4"]


def test_bridge_does_not_emit_a_newick_reserved_separator(dedup_artifacts):
    """':' would read as a branch length and force quoting of the label."""
    abund, idmap, fasta_idmap = dedup_artifacts
    out = idmap.parent / "idmap.original.tsv"
    bridge_deduplicate_idmap_to_original(idmap, fasta_idmap, out)
    for line in out.read_text().splitlines():
        assert ":" not in line.split("\t", 1)[1]


# ---------- display labels are valid Newick ----------


def test_collapsed_labels_need_no_quoting_in_the_display_newick():
    """A collapsed node used to render as `'seq3@9:seq120@1':2`.

    ':' is Newick's branch-length delimiter, so that label parses as a name
    followed by a length that is not a number; quoting it is legal Newick but
    widely rejected by downstream parsers.
    """
    idmap = normalize_idmap_for_display({"seq1": "seq3@9:seq120@1", "seq2": "seq5@4"})
    assert idmap == {"seq1": "seq3@9|seq120@1", "seq2": "seq5@4"}

    display, warns = build_display_newick("(seq1:2,seq2:1)naive:0;", idmap)
    assert display == "(seq3@9|seq120@1:2,seq5@4:1)naive:0;"
    assert "'" not in display
    assert warns == []


def test_normalize_leaves_single_ids_untouched():
    assert normalize_idmap_for_display({"seq2": "seq5@4"}) == {"seq2": "seq5@4"}


def test_quoting_still_protects_ids_with_genuinely_reserved_characters():
    """Original IDs are the user's; a comma in one still has to be quoted."""
    display, _ = build_display_newick("(seq1:2)naive:0;", {"seq1": "clone,1"})
    assert display == "('clone,1':2)naive:0;"
