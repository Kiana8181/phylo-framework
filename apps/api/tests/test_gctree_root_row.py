"""GCtree's synthesized germline row on the AIRR / Change-O tabular path.

GCtree roots the tree on a germline sequence it expects to find in the alignment,
but an AIRR / Change-O export usually contains only observed sequences. When the
user says their table has no germline row, preprocessing adds one from an ID and
an aligned sequence they supply.

The awkward part is *where*: the row has to land under the user's own column
names when column mapping is on, and it has to be in the file before the shared
structural validator sees it. These tests pin both, plus the two mistakes the
user can actually make — a sequence of the wrong length, and an ID already in use.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_gctree_root_row.py
"""
from __future__ import annotations

import csv
from pathlib import Path

import pytest

from apps.api.preprocess.prepare_input import PreprocessError, prepare_input_for_method

ADAPTER = "airr_or_changeo_table_adapter"
GERMLINE = "ACGTACGTAC"


def _write(tmp_path: Path, name: str, header: list[str], rows: list[list[str]]) -> Path:
    path = tmp_path / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        writer.writerows(rows)
    return path


def _canonical_table(tmp_path: Path, name: str = "input.tsv") -> Path:
    return _write(
        tmp_path,
        name,
        ["sequence_id", "sequence_alignment", "clone_id"],
        [
            ["s1", "ACGTACGTAA", "c1"],
            ["s2", "ACGTACGTAG", "c1"],
            ["s3", "ACGTACGTAT", "c1"],
        ],
    )


def _params(**overrides):
    params = {
        "input_scenario": ADAPTER,
        "germline_row_present": "no",
        "root_sequence_id": "GL",
        "root_sequence_alignment": GERMLINE,
    }
    params.update(overrides)
    return params


def _prepare(src: Path, params: dict, tmp_path: Path):
    return prepare_input_for_method(
        "gctree", src, params=params, work_dir=tmp_path / "work"
    )


def _fasta_records(path: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for block in path.read_text(encoding="utf-8").split(">"):
        if not block.strip():
            continue
        header, _, body = block.partition("\n")
        records.append((header.strip(), body.replace("\n", "").strip()))
    return records


def _step(prepared, name: str):
    return next((s for s in prepared.applied_steps if s["step"] == name), None)


# --------------------------------------------------------------- the happy path

def test_root_row_becomes_the_first_fasta_record(tmp_path):
    prepared = _prepare(_canonical_table(tmp_path), _params(), tmp_path)

    records = _fasta_records(prepared.final_path)
    assert records[0] == ("GL", GERMLINE)
    assert [rid for rid, _ in records] == ["GL", "s1", "s2", "s3"]


def test_other_columns_of_the_root_row_are_left_empty(tmp_path):
    prepared = _prepare(_canonical_table(tmp_path), _params(), tmp_path)

    step = _step(prepared, "insert_root_row")
    assert step is not None
    with Path(step["output_path"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))

    assert rows[0] == {"sequence_id": "GL", "sequence_alignment": GERMLINE, "clone_id": ""}


def test_the_step_is_logged_with_the_columns_it_used(tmp_path):
    prepared = _prepare(_canonical_table(tmp_path), _params(), tmp_path)

    entry = next(e for e in prepared.log_entries if e["step"].endswith("insert_root_row"))
    assert "GL" in entry["out"]
    assert "sequence_id" in entry["out"]
    assert "sequence_alignment" in entry["out"]


# ------------------------------------------------------------- column mapping

def test_row_lands_under_the_user_s_own_column_names(tmp_path):
    src = _write(
        tmp_path,
        "mapped.tsv",
        ["Seq.ID", "nt alignment", "clone_id"],
        [
            ["s1", "ACGTACGTAA", "c1"],
            ["s2", "ACGTACGTAG", "c1"],
        ],
    )
    params = _params(
        doMapping=True,
        column_map={"sequence_id": "Seq.ID", "sequence_alignment": "nt alignment"},
    )

    prepared = _prepare(src, params, tmp_path)

    # Written under the source headers, before the rename step runs...
    step = _step(prepared, "insert_root_row")
    with Path(step["output_path"]).open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    assert rows[0]["Seq.ID"] == "GL"
    assert rows[0]["nt alignment"] == GERMLINE

    # ...and carried through the rename into the FASTA.
    assert _fasta_records(prepared.final_path)[0] == ("GL", GERMLINE)


# ------------------------------------------------------- when nothing is added

@pytest.mark.parametrize("answer", ["yes", None])
def test_table_is_untouched_when_it_already_carries_the_row(answer, tmp_path):
    """A missing answer is the pre-existing behaviour: params written before the
    question existed must keep meaning "the row is already there"."""
    src = _write(
        tmp_path,
        "with_root.tsv",
        ["sequence_id", "sequence_alignment", "clone_id"],
        [["GL", GERMLINE, "c1"], ["s1", "ACGTACGTAA", "c1"]],
    )
    params = {"input_scenario": ADAPTER, "root": "GL"}
    if answer is not None:
        params["germline_row_present"] = answer

    prepared = _prepare(src, params, tmp_path)

    assert _step(prepared, "insert_root_row") is None
    assert [rid for rid, _ in _fasta_records(prepared.final_path)] == ["GL", "s1"]


def test_question_does_not_apply_to_the_plain_fasta_scenario(tmp_path):
    prepared = _prepare(
        _canonical_table(tmp_path),
        _params(input_scenario="aligned_fasta_with_root"),
        tmp_path,
    )

    assert _step(prepared, "insert_root_row") is None


# ------------------------------------------------------------------- rejections

def test_a_germline_of_the_wrong_length_is_rejected(tmp_path):
    params = _params(root_sequence_alignment=GERMLINE[:-1])

    with pytest.raises(PreprocessError) as excinfo:
        _prepare(_canonical_table(tmp_path), params, tmp_path)

    err = excinfo.value
    assert err.code == "ROOT_SEQUENCE_LENGTH_MISMATCH"
    assert "9" in err.message and "10" in err.message
    assert err.details["step"] == "insert_root_row"


def test_an_id_already_in_the_table_is_rejected(tmp_path):
    params = _params(root_sequence_id="s2")

    with pytest.raises(PreprocessError) as excinfo:
        _prepare(_canonical_table(tmp_path), params, tmp_path)

    err = excinfo.value
    assert err.code == "ROOT_ID_ALREADY_PRESENT"
    assert "'s2'" in err.message


@pytest.mark.parametrize(
    "overrides",
    [
        {"root_sequence_id": ""},
        {"root_sequence_alignment": ""},
        {"root_sequence_alignment": "   "},
    ],
)
def test_a_missing_id_or_sequence_is_rejected(overrides, tmp_path):
    with pytest.raises(PreprocessError) as excinfo:
        _prepare(_canonical_table(tmp_path), _params(**overrides), tmp_path)

    assert excinfo.value.code == "MISSING_ROOT_SEQUENCE"


def test_a_germline_with_stray_characters_is_rejected_by_the_shared_validator(tmp_path):
    """The row is inserted before validation precisely so it gets the same
    character check as every other row."""
    params = _params(root_sequence_alignment="ACGTACGTAZ")

    with pytest.raises(PreprocessError) as excinfo:
        _prepare(_canonical_table(tmp_path), params, tmp_path)

    assert excinfo.value.code == "INPUT_INVALID_SEQUENCE_CHARACTERS"
