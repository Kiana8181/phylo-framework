"""Unit tests for inconsistent-row-width reporting in table normalization.

These verify that when a tabular upload has a row whose column count differs
from the header, the raised error is self-describing (names the offending row
and the expected/actual widths) so the failure is diagnosable from the
user-facing message alone.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_converters_row_width.py
"""
from pathlib import Path

import pytest

from apps.api.preprocess.converters import (
    ConversionError,
    normalize_table_delimiter,
)


def test_row_width_mismatch_message_names_row_and_widths(tmp_path: Path):
    src = tmp_path / "vquest_airr.tsv"
    # Header has 3 columns; row 3 carries an extra trailing tab (4 fields).
    src.write_text(
        "sequence_id\tv_call\tj_call\n"
        "S1\tIGHV1\tIGHJ4\n"
        "S2\tIGHV2\tIGHJ5\t\n",
        encoding="utf-8",
    )
    out = tmp_path / "out.tsv"

    with pytest.raises(ConversionError) as excinfo:
        normalize_table_delimiter(src, out, delimiter="tsv")

    exc = excinfo.value
    assert exc.code == "ROW_WIDTH_MISMATCH"
    # The message alone should pinpoint the failure.
    assert "row 3" in exc.message
    assert "4 column" in exc.message
    assert "header has 3" in exc.message
    # Structured details remain available for programmatic consumers.
    assert exc.details["row_number"] == 3
    assert exc.details["expected_columns"] == 3
    assert exc.details["actual_columns"] == 4
