"""Framework-level structural validation of tabular inputs.

Covers the eight defects from the thesis's negative-test matrix (NT-01..NT-08),
and — the point of the exercise — asserts that all four methods reject each one
identically, before dispatch. Previously only GCtree's table->FASTA path checked
any of this, so the same malformed file failed four different ways.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_validate_input.py
"""
from __future__ import annotations

from pathlib import Path

import pytest

from apps.api.preprocess.prepare_input import PreprocessError, prepare_input_for_method
from apps.api.preprocess.validate_input import (
    InputValidationError,
    validate_airr_table,
)

METHODS = ["dowser", "gctree", "clonaltree", "brepphylo"]

HEADER = "sequence_id\tsequence_alignment\tclone_id\tgermline_alignment_d_mask\tv_call\tj_call\tjunction_length"


def _row(sid: str, seq: str) -> str:
    return f"{sid}\t{seq}\tc1\tACGTACGT\tIGHV3-49*03\tIGHJ5*02\t8"


def _table(rows: list[str], header: str = HEADER) -> str:
    return "\n".join([header, *rows]) + "\n"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


VALID = _table([_row("s1", "ACGTACGT"), _row("s2", "ACGTACGA"), _row("s3", "ACGTTCGA")])


def _prepare(method: str, src: Path, tmp_path: Path):
    return prepare_input_for_method(
        method, src, params={}, work_dir=tmp_path / f"w-{method}"
    )


def _expect_rejection(method: str, src: Path, tmp_path: Path) -> PreprocessError:
    with pytest.raises(PreprocessError) as excinfo:
        _prepare(method, src, tmp_path)
    return excinfo.value


# ------------------------------------------------- the eight defects, uniformly

@pytest.mark.parametrize("method", METHODS)
def test_nt01_missing_required_column_is_rejected(method, tmp_path):
    src = _write(
        tmp_path,
        "nt01.tsv",
        _table(
            ["ACGTACGT\tc1\tACGTACGT\tIGHV3-49*03\tIGHJ5*02\t8"],
            header="sequence_alignment\tclone_id\tgermline_alignment_d_mask\tv_call\tj_call\tjunction_length",
        ),
    )
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_MISSING_COLUMNS"
    assert "sequence_id" in err.message


@pytest.mark.parametrize("method", METHODS)
def test_nt02_empty_sequence_is_rejected(method, tmp_path):
    src = _write(tmp_path, "nt02.tsv", _table([_row("s1", "ACGTACGT"), _row("s2", "")]))
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_EMPTY_SEQUENCE"
    # Names the offending row, not just the fact of a problem.
    assert "3" in err.message


@pytest.mark.parametrize("method", METHODS)
def test_nt03_invalid_characters_are_rejected(method, tmp_path):
    src = _write(
        tmp_path, "nt03.tsv", _table([_row("s1", "ACGTX1*T"), _row("s2", "ACGTACGA")])
    )
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_INVALID_SEQUENCE_CHARACTERS"
    # The GCtree NT-03 behaviour was the quality bar: name the characters.
    for char in ("1", "*", "X"):
        assert char in err.message


# NT-04 (unequal alignment lengths) and NT-07 (duplicate identifiers) are
# deliberately NOT core checks: whether either is fatal depends on the method
# and its parameters, so both are enforced by each service's own validator.
# See `docs/validation-coverage.md` and the tests below.

def test_ragged_alignment_is_not_a_core_concern(tmp_path):
    """Core reports the spread but does not judge it; ClonalTree without
    `use_input_alignment` and BrepPhylo in `raw_sequence` mode both re-align."""
    src = _write(
        tmp_path,
        "ragged.tsv",
        _table([_row("s1", "ACGTACGT"), _row("s2", "ACGTACGTA")]),
    )
    # GCtree is excluded: its table->FASTA adapter enforces both properties as
    # part of its own input contract, which is the correct place for them.
    for method in ["dowser", "clonaltree", "brepphylo"]:
        prepared = _prepare(method, src, tmp_path)
        stats = prepared.stats["input_validation"]
        assert stats["distinct_alignment_lengths"] == 2
        assert "alignment_lengths" not in stats["checked"]


def test_duplicate_identifiers_are_not_a_core_concern(tmp_path):
    """Uniqueness scope is global for three methods and per-clone for
    BrepPhylo, so it is enforced in-service, not here."""
    src = _write(
        tmp_path, "dup.tsv", _table([_row("s1", "ACGTACGT"), _row("s1", "ACGTACGA")])
    )
    for method in ["dowser", "clonaltree", "brepphylo"]:
        prepared = _prepare(method, src, tmp_path)
        assert prepared.stats["input_validation"]["rows"] == 2


@pytest.mark.parametrize("method", METHODS)
def test_nt05_empty_file_is_rejected(method, tmp_path):
    src = _write(tmp_path, "nt05.tsv", "")
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_EMPTY_FILE"


@pytest.mark.parametrize("method", METHODS)
def test_nt06_header_only_file_is_rejected(method, tmp_path):
    src = _write(tmp_path, "nt06.tsv", HEADER + "\n")
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_NO_DATA_ROWS"
    # NT-06's old failure was that the message did not reveal the cause.
    assert "no data rows" in err.message.lower()


def test_nt07_duplicate_sequence_id_is_rejected_on_the_gctree_path(tmp_path):
    """GCtree's table->FASTA adapter enforces uniqueness because FASTA headers
    must be unique. That is a property of its own input contract, so it stays
    on the GCtree path rather than moving into core."""
    src = _write(
        tmp_path, "nt07.tsv", _table([_row("s1", "ACGTACGT"), _row("s1", "ACGTACGA")])
    )
    err = _expect_rejection("gctree", src, tmp_path)
    assert err.code == "DUPLICATE_IDS"
    # The reported NT-07 defect was that this named the wrong cause.
    assert "GCTREE_ALIGNMENT_REQUIRED" not in err.code
    assert "s1" in err.message and "unique" in err.message


def test_gctree_empty_identifier_names_the_identifier_not_the_alignment(tmp_path):
    """NT-08 previously returned GCTREE_ALIGNMENT_REQUIRED, which named the
    wrong cause. Core catches an empty id first; this pins the GCtree-path
    message for the case core does not reach."""
    from apps.api.preprocess.converters import convert_table_to_aligned_fasta, ConversionError

    src = _write(tmp_path, "emptyid.tsv", "sequence_id\tsequence_alignment\ns1\tACGT\n\tACGA\n")
    with pytest.raises(ConversionError) as excinfo:
        convert_table_to_aligned_fasta(
            src, tmp_path / "out.fasta", aligned_seq_column="sequence_alignment", delimiter="tsv"
        )
    assert excinfo.value.code == "EMPTY_ID"


@pytest.mark.parametrize("method", METHODS)
def test_nt08_empty_sequence_id_is_rejected(method, tmp_path):
    src = _write(
        tmp_path, "nt08.tsv", _table([_row("", "ACGTACGT"), _row("s2", "ACGTACGA")])
    )
    err = _expect_rejection(method, src, tmp_path)
    assert err.code == "INPUT_EMPTY_SEQUENCE_ID"
    assert "2" in err.message


# --------------------------------------------------------------- uniformity

@pytest.mark.parametrize(
    "name,content,expected_code",
    [
        ("empty", "", "INPUT_EMPTY_FILE"),
        ("header_only", HEADER + "\n", "INPUT_NO_DATA_ROWS"),
        ("missing_col", _table(["ACGTACGT\tc1\tACGTACGT\tIGHV3-49*03\tIGHJ5*02\t8"],
                               header="sequence_alignment\tclone_id\tgermline_alignment_d_mask\tv_call\tj_call\tjunction_length"),
         "INPUT_MISSING_COLUMNS"),
        ("empty_id", _table([_row("", "ACGTACGT")]), "INPUT_EMPTY_SEQUENCE_ID"),
        ("empty_seq", _table([_row("s1", "")]), "INPUT_EMPTY_SEQUENCE"),
        ("bad_chars", _table([_row("s1", "ACGTXXXX")]), "INPUT_INVALID_SEQUENCE_CHARACTERS"),
    ],
)
def test_every_method_gives_the_same_code_and_message(name, content, expected_code, tmp_path):
    """One defect, one code, one message — for the checks core actually owns."""
    outcomes = {}
    for method in METHODS:
        src = _write(tmp_path, f"{name}-{method}.tsv", content)
        err = _expect_rejection(method, src, tmp_path)
        outcomes[method] = (err.code, err.message)

    codes = {code for code, _ in outcomes.values()}
    messages = {message for _, message in outcomes.values()}
    assert codes == {expected_code}, outcomes
    assert len(messages) == 1, outcomes


# ------------------------------------------------------ no regression on valid

@pytest.mark.parametrize("method", METHODS)
def test_valid_input_still_passes(method, tmp_path):
    src = _write(tmp_path, "valid.tsv", VALID)
    prepared = _prepare(method, src, tmp_path)
    assert prepared.stats["input_validation"]["rows"] == 3


def test_germline_row_with_masked_positions_is_accepted(tmp_path):
    """The GCtree evaluation input carries a `GL` row whose germline contains
    masked N positions. Rejecting N would break every clone."""
    src = _write(
        tmp_path,
        "gl.tsv",
        _table([_row("s1", "ACGTACGT"), _row("GL", "ACGTNNNN")]),
    )
    prepared = _prepare("gctree", src, tmp_path)
    assert prepared.stats["input_validation"]["rows"] == 2


def test_iupac_ambiguity_codes_are_accepted(tmp_path):
    """Rejecting IUPAC codes would throw out valid AIRR data."""
    src = _write(tmp_path, "iupac.tsv", _table([_row("s1", "ACGTRYSW"), _row("s2", "ACGTKMBD")]))
    prepared = _prepare("dowser", src, tmp_path)
    assert prepared.stats["input_validation"]["rows"] == 2


def test_both_gap_conventions_are_accepted(tmp_path):
    """IMGT uses '.', conventional alignments use '-'; both appear in the data."""
    src = _write(tmp_path, "gaps.tsv", _table([_row("s1", "ACGT..--"), _row("s2", "ACGTACGA")]))
    prepared = _prepare("dowser", src, tmp_path)
    assert prepared.stats["input_validation"]["rows"] == 2


def test_blank_padding_rows_do_not_trip_the_row_checks(tmp_path):
    """Excel exports append blank rows; those are dropped, not reported as
    empty identifiers."""
    src = _write(tmp_path, "padded.tsv", VALID + "\t\t\t\t\t\t\n\t\t\t\t\t\t\n")
    prepared = _prepare("dowser", src, tmp_path)
    assert prepared.stats["input_validation"]["rows"] == 3


# --------------------------------------------------------- unit-level details

def test_validation_reports_all_invalid_characters_not_just_the_first(tmp_path):
    src = _write(tmp_path, "chars.tsv", _table([_row("s1", "ACGTX1*?")]))
    with pytest.raises(InputValidationError) as excinfo:
        validate_airr_table(src, delimiter="\t")
    assert set(excinfo.value.details["invalid_characters"]) == {"X", "1", "*", "?"}


def test_whitespace_only_file_counts_as_empty(tmp_path):
    src = _write(tmp_path, "ws.tsv", "\n\n\n")
    with pytest.raises(InputValidationError) as excinfo:
        validate_airr_table(src, delimiter="\t")
    assert excinfo.value.code == "INPUT_EMPTY_FILE"


def test_custom_column_names_are_honoured(tmp_path):
    """BrepPhylo names its columns through flat params rather than a map."""
    src = _write(tmp_path, "custom.tsv", "tip\tseq\nA\tACGT\n\tACGA\n")
    with pytest.raises(InputValidationError) as excinfo:
        validate_airr_table(src, delimiter="\t", id_column="tip", sequence_column="seq")
    assert excinfo.value.code == "INPUT_EMPTY_SEQUENCE_ID"


def test_row_numbers_are_true_file_lines_not_post_filter_positions(tmp_path):
    """Blank padding rows are dropped before the checks run, but a surviving
    row must still be reported at the line it actually occupies — otherwise
    every number after a blank row points a user at the wrong place."""
    src = _write(
        tmp_path,
        "blank-between.tsv",
        "sequence_id\tsequence_alignment\n"  # line 1
        "s1\tACGT\n"                          # line 2
        "\t\n"                                # line 3 (blank padding)
        "s2\tACGT\n"                          # line 4
        "\tACGT\n",                           # line 5 -- the empty identifier
    )
    with pytest.raises(InputValidationError) as excinfo:
        validate_airr_table(src, delimiter="\t")
    assert excinfo.value.details["lines"] == [5]
    assert "row 5" in excinfo.value.message


def test_invalid_character_lines_survive_blank_rows_too(tmp_path):
    src = _write(
        tmp_path,
        "blank-chars.tsv",
        "sequence_id\tsequence_alignment\ns1\tACGT\n\t\ns2\tACGT\ns3\tACGZ\n",
    )
    with pytest.raises(InputValidationError) as excinfo:
        validate_airr_table(src, delimiter="\t")
    assert excinfo.value.details["lines"] == [5]
