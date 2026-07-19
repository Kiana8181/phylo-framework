"""Unit tests for ClonalTree in-service input validation.

The validator uses only the stdlib, so these run without the scientific deps.

Run from services/clonaltree:
    python -m pytest tests/test_validators.py
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from validators import (  # noqa: E402
    REQUIRED_COLUMNS,
    validate_clonaltree_input,
)

# Columns a minimal, fully-valid ClonalTree AIRR input carries. Includes the
# hard-required set plus the recommended base + refinement columns so the
# golden input produces NO warnings.
_FULL_COLUMNS = [
    "sequence_id",
    "sequence_alignment",
    "cdr3_aa",
    "v_call",
    "j_call",
    "productive",
    "d_call",
    "junction_aa",
    "j_sequence_alignment",
    "v_sequence_alignment",
    "j_sequence_alignment_aa",
    "v_sequence_alignment_aa",
]


def _row(seq_id: str, alignment: str = "ACGTACGT", **overrides) -> dict:
    row = {
        "sequence_id": seq_id,
        "sequence_alignment": alignment,
        "cdr3_aa": "CARWDY",
        "v_call": "IGHV1-2",
        "j_call": "IGHJ4",
        "productive": "T",
        "d_call": "IGHD3-10",
        "junction_aa": "CARWDYW",
        "j_sequence_alignment": "ACGT",
        "v_sequence_alignment": "ACGT",
        "j_sequence_alignment_aa": "TS",
        "v_sequence_alignment_aa": "TS",
    }
    row.update(overrides)
    return row


def _write_tsv(path: Path, columns, rows, *, delimiter: str = "\t") -> Path:
    lines = [delimiter.join(columns)]
    for row in rows:
        lines.append(delimiter.join(str(row.get(c, "")) for c in columns))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _golden(tmp_path: Path) -> Path:
    rows = [_row("seq1"), _row("seq2"), _row("seq3")]
    return _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, rows)


# ---------------------------------------------------------------------------
# Golden / anti-regression: a valid input MUST pass with no error and no
# warnings. This is the "don't break what works" guard.
# ---------------------------------------------------------------------------
def test_golden_valid_input_passes_clean(tmp_path: Path):
    result = validate_clonaltree_input(_golden(tmp_path), {})
    assert result.ok is True
    assert result.error is None
    assert result.warnings == []


def test_golden_valid_input_passes_with_refinement_enabled(tmp_path: Path):
    result = validate_clonaltree_input(_golden(tmp_path), {"use_refinement": True})
    assert result.ok is True
    assert result.warnings == []


def test_csv_delimited_input_is_accepted(tmp_path: Path):
    path = _write_tsv(
        tmp_path / "airr.csv",
        _FULL_COLUMNS,
        [_row("seq1"), _row("seq2")],
        delimiter=",",
    )
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert result.warnings == []


def test_bom_prefixed_header_still_matches(tmp_path: Path):
    path = tmp_path / "airr.tsv"
    _write_tsv(path, _FULL_COLUMNS, [_row("seq1"), _row("seq2")])
    # Prepend a UTF-8 BOM to the file.
    raw = path.read_bytes()
    path.write_bytes(b"\xef\xbb\xbf" + raw)
    result = validate_clonaltree_input(path, {})
    assert result.ok is True, result.error


# ---------------------------------------------------------------------------
# Hard-fail cases.
# ---------------------------------------------------------------------------
def test_missing_required_column_fails(tmp_path: Path):
    columns = [c for c in _FULL_COLUMNS if c != "cdr3_aa"]
    path = _write_tsv(tmp_path / "airr.tsv", columns, [_row("seq1"), _row("seq2")])
    result = validate_clonaltree_input(path, {})
    assert result.ok is False
    assert result.error_details.get("code") == "missing_required_columns"
    assert "cdr3_aa" in result.error_details.get("missing_columns", [])


def test_empty_file_fails(tmp_path: Path):
    path = tmp_path / "airr.tsv"
    path.write_text("", encoding="utf-8")
    result = validate_clonaltree_input(path, {})
    assert result.ok is False
    assert result.error_details.get("code") == "unreadable_input"


def test_header_only_no_rows_fails(tmp_path: Path):
    path = _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, [])
    result = validate_clonaltree_input(path, {})
    assert result.ok is False
    assert result.error_details.get("code") == "no_data_rows"


def test_missing_file_fails(tmp_path: Path):
    result = validate_clonaltree_input(tmp_path / "does_not_exist.tsv", {})
    assert result.ok is False
    assert result.error_details.get("code") == "unreadable_input"


def test_empty_sequence_id_fails(tmp_path: Path):
    rows = [_row("seq1"), _row(""), _row("seq3")]
    path = _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is False
    assert result.error_details.get("code") == "empty_sequence_id"


def test_duplicate_sequence_id_fails(tmp_path: Path):
    rows = [_row("seq1"), _row("seq2"), _row("seq1")]
    path = _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is False
    assert result.error_details.get("code") == "duplicate_sequence_id"
    assert "seq1" in result.error_details.get("examples", [])


# ---------------------------------------------------------------------------
# Warning-only cases: ok stays True, run proceeds.
# ---------------------------------------------------------------------------
def test_incomplete_rows_warn_but_pass(tmp_path: Path):
    rows = [_row("seq1"), _row("seq2", cdr3_aa=""), _row("seq3", v_call="")]
    path = _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert any("cdr3_aa" in w for w in result.warnings)
    assert any("v_call" in w for w in result.warnings)


def test_missing_recommended_column_warns_but_passes(tmp_path: Path):
    columns = [c for c in _FULL_COLUMNS if c != "productive"]
    rows = [_row("seq1"), _row("seq2")]
    path = _write_tsv(tmp_path / "airr.tsv", columns, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert any("productive" in w for w in result.warnings)


def test_missing_refinement_column_warns_when_refinement_enabled(tmp_path: Path):
    columns = [c for c in _FULL_COLUMNS if c != "v_sequence_alignment"]
    rows = [_row("seq1"), _row("seq2")]
    path = _write_tsv(tmp_path / "airr.tsv", columns, rows)
    result = validate_clonaltree_input(path, {"use_refinement": True})
    assert result.ok is True
    assert any("Refinement" in w for w in result.warnings)


def test_missing_refinement_column_silent_when_refinement_disabled(tmp_path: Path):
    columns = [c for c in _FULL_COLUMNS if c != "v_sequence_alignment"]
    rows = [_row("seq1"), _row("seq2")]
    path = _write_tsv(tmp_path / "airr.tsv", columns, rows)
    result = validate_clonaltree_input(path, {"use_refinement": False})
    assert result.ok is True
    assert not any("Refinement" in w for w in result.warnings)


def test_alignment_length_mismatch_warns_but_passes(tmp_path: Path):
    rows = [
        _row("seq1", sequence_alignment="ACGTACGT"),
        _row("seq2", sequence_alignment="ACGT"),
    ]
    path = _write_tsv(tmp_path / "airr.tsv", _FULL_COLUMNS, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert any("length" in w.lower() for w in result.warnings)


def test_unrecognized_column_warns_but_passes(tmp_path: Path):
    columns = _FULL_COLUMNS + ["totally_custom_field"]
    rows = [_row("seq1"), _row("seq2")]
    path = _write_tsv(tmp_path / "airr.tsv", columns, rows)
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert any("totally_custom_field" in w for w in result.warnings)


def test_blank_padding_rows_are_ignored(tmp_path: Path):
    path = tmp_path / "airr.tsv"
    _write_tsv(path, _FULL_COLUMNS, [_row("seq1"), _row("seq2")])
    # Append fully-blank trailing lines like Excel padding.
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\t".join("" for _ in _FULL_COLUMNS) + "\n")
        handle.write("\t".join("" for _ in _FULL_COLUMNS) + "\n")
    result = validate_clonaltree_input(path, {})
    assert result.ok is True
    assert result.warnings == []


def test_required_columns_constant_is_the_expected_set():
    assert set(REQUIRED_COLUMNS) == {
        "sequence_id",
        "sequence_alignment",
        "cdr3_aa",
        "v_call",
        "j_call",
    }
