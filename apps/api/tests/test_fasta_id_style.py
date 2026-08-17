"""Covers the classifier behind GET /datasets/{id}/fasta-id-style.

The GCtree form uses this to decide whether to ask what the number in a
``seq3@9`` header means. Getting the verdict wrong either hides a question the
run cannot proceed without, or asks it when it makes no sense.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_fasta_id_style.py
"""
import pytest

from apps.api.services.fasta_id_style import (
    STYLE_AT_ABUNDANCE,
    STYLE_OTHER_AT,
    STYLE_PLAIN,
    classify_fasta_headers,
    extract_fasta_headers,
)


@pytest.mark.parametrize(
    "headers, expected",
    [
        (["naive@0", "seq3@9"], STYLE_AT_ABUNDANCE),
        (["naive", "seq3"], STYLE_PLAIN),
        (["naive@0", "seq3"], STYLE_OTHER_AT),
        (["naive@0", "seq3@IgG"], STYLE_OTHER_AT),  # suffix is not an integer
        (["a@1@2"], STYLE_OTHER_AT),  # two '@' is not the convention
        ([], STYLE_PLAIN),
        ([""], STYLE_PLAIN),
    ],
)
def test_classification(headers, expected):
    assert classify_fasta_headers(headers) == expected


def test_description_after_the_id_is_ignored():
    headers = ["naive@0 germline sequence", "seq3@9 clone 4"]
    assert classify_fasta_headers(headers) == STYLE_AT_ABUNDANCE


def test_headers_are_extracted_from_fasta_text():
    text = ">naive@0\nACGT\nACGT\n>seq3@9\nACGT\n"
    assert extract_fasta_headers(text) == ["naive@0", "seq3@9"]


def test_truncated_read_drops_a_possibly_half_written_header():
    # Without the drop, ">seq3" reads as a plain ID and flips the verdict.
    text = ">naive@0\nACGT\n>seq3"
    assert classify_fasta_headers(extract_fasta_headers(text)) == STYLE_OTHER_AT
    assert (
        classify_fasta_headers(extract_fasta_headers(text, truncated=True))
        == STYLE_AT_ABUNDANCE
    )


def test_classification_matches_the_gctree_service():
    """The regex is duplicated across deploy units; keep the verdicts identical."""
    import os
    import sys
    import tempfile
    from pathlib import Path

    os.environ.setdefault("METHOD_JOBS_DIR", tempfile.mkdtemp(prefix="gctree-jobs-"))
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "services" / "gctree"))
    from app import FastaRecord, classify_fasta_id_style  # noqa: PLC0415

    for headers in (["naive@0", "seq3@9"], ["naive", "seq3"], ["naive@0", "seq3"]):
        records = [FastaRecord(original_id=h, sequence="ACGT") for h in headers]
        assert classify_fasta_id_style(records) == classify_fasta_headers(headers)
