"""Unit tests for which ID GCtree is told to root on.

The tabular-adapter path lets the user say their table has no germline row, in
which case the framework builds one from ``root_sequence_id`` /
``root_sequence_alignment`` and appends it before converting the table to FASTA.
The form hides ``root`` in that case and therefore does not submit it, so a
service that only read ``root`` would fall back to ``"GL"`` and then fail the
header lookup in ``remap_fasta_ids_for_gctree`` — with a message naming an ID the
user never typed.

Run from services/gctree:
    python -m pytest tests/test_resolve_root_id.py
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

from app import SC_AIRR, SC_ALIGNED, resolve_root_id  # noqa: E402


def test_uses_the_synthesized_id_when_the_framework_added_the_row():
    assert (
        resolve_root_id(
            {
                "input_scenario": SC_AIRR,
                "germline_row_present": "no",
                "root_sequence_id": "naive",
                "root_sequence_alignment": "ACGT",
            }
        )
        == "naive"
    )


def test_uses_the_named_row_when_the_table_already_carries_it():
    assert (
        resolve_root_id(
            {
                "input_scenario": SC_AIRR,
                "germline_row_present": "yes",
                "root": "IGHV3-23",
            }
        )
        == "IGHV3-23"
    )


def test_a_missing_answer_means_the_row_is_already_there():
    """Params written before the question existed must keep working."""
    assert resolve_root_id({"input_scenario": SC_AIRR, "root": "IGHV3-23"}) == "IGHV3-23"


def test_the_fasta_scenario_is_unaffected_by_the_answer():
    params = {
        "input_scenario": SC_ALIGNED,
        "germline_row_present": "no",
        "root": "IGHV3-23",
        "root_sequence_id": "naive",
    }
    assert resolve_root_id(params) == "IGHV3-23"


@pytest.mark.parametrize("synthesized", ["", "   ", None])
def test_falls_back_rather_than_rooting_on_an_empty_id(synthesized):
    """Preprocessing rejects a blank ID before we get here, so this only has to
    avoid producing an empty ``--root`` argument."""
    assert (
        resolve_root_id(
            {
                "input_scenario": SC_AIRR,
                "germline_row_present": "no",
                "root_sequence_id": synthesized,
                "root": "IGHV3-23",
            }
        )
        == "IGHV3-23"
    )


def test_defaults_to_GL_when_nothing_is_given():
    assert resolve_root_id({}) == "GL"
