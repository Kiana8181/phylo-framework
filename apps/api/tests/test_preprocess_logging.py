"""Tests for the preprocessing execution log emitted with each run.

Every preprocessing step that actually runs appends a RunLogEntry-shaped record
({step, ok, out}) to `PreparedInput.log_entries`. The worker persists these into
the run's `result["logs"]`, which is what the result panel's Logs section
renders, so these tests pin both the content and the shape.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_preprocess_logging.py
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest

from apps.api.database.models import RunStatus, User
from apps.api.preprocess.prepare_input import (
    PREPROCESS_LOG_PREFIX,
    prepare_input_for_method,
)
from apps.api.repositories.run_repository import RunRepository
from apps.api.services.tree_contract import assemble_unified_tree_result
from apps.api.workers.run_worker import _merge_preprocess_logs

DOWSER_MAP = {
    "sequence_id": "seqID",
    "clone_id": "cloneID",
    "sequence_alignment": "seqAlign",
    "germline_alignment_d_mask": "germAlign",
    "v_call": "vcall",
    "j_call": "jcall",
    "junction_length": "junclen",
}


def _entry(entries, step):
    """The single entry for `step`, or None."""
    want = f"{PREPROCESS_LOG_PREFIX}.{step}"
    found = [e for e in entries if e["step"] == want]
    assert len(found) <= 1, f"expected at most one {want}, got {len(found)}"
    return found[0] if found else None


def _steps(entries):
    return [e["step"] for e in entries]


def test_entries_match_the_run_log_entry_shape(tmp_path: Path):
    """The client renders {step, ok, cmd, out} without special-casing."""
    src = tmp_path / "clones.tsv"
    src.write_text("sequence_id\tsequence_alignment\ns1\tACGT\n", encoding="utf-8")

    prepared = prepare_input_for_method(
        "gctree", src, params={}, work_dir=tmp_path / "w"
    )

    assert prepared.log_entries
    for entry in prepared.log_entries:
        assert set(entry) <= {"step", "ok", "cmd", "out"}
        assert isinstance(entry["step"], str)
        assert isinstance(entry["ok"], bool)
        assert isinstance(entry["out"], str) and entry["out"]
        assert entry["step"].startswith(f"{PREPROCESS_LOG_PREFIX}.")


def test_column_mapping_logs_every_rename_from_to(tmp_path: Path):
    src = tmp_path / "clones.tsv"
    src.write_text(
        "seqID\tcloneID\tseqAlign\tgermAlign\tvcall\tjcall\tjunclen\n"
        "a1\tc1\tACGT\tACGT\tIGHV1\tIGHJ1\t12\n",
        encoding="utf-8",
    )

    prepared = prepare_input_for_method(
        "dowser",
        src,
        params={"doMapping": True, "column_map": DOWSER_MAP},
        work_dir=tmp_path / "w",
    )

    rename = _entry(prepared.log_entries, "rename_table_columns")
    assert rename is not None and rename["ok"] is True
    assert "columns renamed=7" in rename["out"]
    for canonical, source in DOWSER_MAP.items():
        assert f"{source}->{canonical}" in rename["out"]


def test_format_conversion_logs_the_resulting_file_type(tmp_path: Path):
    """GCtree tabular input is exported to aligned FASTA."""
    src = tmp_path / "aligned.tsv"
    src.write_text(
        "sequence_id\tsequence_alignment\n"
        "s1\tACGTACGT\n"
        "s2\tACGTACGA\n"
        "s3\tACGTTCGA\n",
        encoding="utf-8",
    )

    prepared = prepare_input_for_method(
        "gctree", src, params={}, work_dir=tmp_path / "w"
    )

    convert = _entry(prepared.log_entries, "convert_table_to_aligned_fasta")
    assert convert is not None and convert["ok"] is True
    assert "table -> aligned FASTA" in convert["out"]
    assert "result=.fasta" in convert["out"]
    assert "records=3" in convert["out"]
    assert "alignment length=8" in convert["out"]
    assert prepared.final_ext == "fasta"


def test_csv_to_tsv_conversion_is_logged(tmp_path: Path):
    src = tmp_path / "repertoire.csv"
    src.write_text(
        "sequence_id,sequence_alignment\ns1,ACGT\ns2,ACGA\n", encoding="utf-8"
    )

    prepared = prepare_input_for_method(
        "clonaltree", src, params={}, work_dir=tmp_path / "w"
    )

    convert = _entry(prepared.log_entries, "convert_csv_to_tsv")
    assert convert is not None
    assert "converted CSV -> TSV" in convert["out"]
    assert "result=.tsv" in convert["out"]
    assert "rows=2" in convert["out"]


def test_sanitization_statistics_are_recorded(tmp_path: Path):
    """A semicolon export with a BOM and blank padding rows reports all three."""
    src = tmp_path / "excel.csv"
    src.write_bytes(
        b"\xef\xbb\xbfsequence_id;sequence_alignment\n"
        b"s1;ACGT\n"
        b"s2;ACGA\n"
        b";\n"
        b";\n"
    )

    prepared = prepare_input_for_method(
        "clonaltree", src, params={}, work_dir=tmp_path / "w"
    )

    norm = _entry(prepared.log_entries, "normalize_table_delimiter")
    assert norm is not None
    assert "delimiter=semicolon->comma" in norm["out"]
    assert "blank rows dropped=2" in norm["out"]
    assert "byte-order mark stripped=yes" in norm["out"]
    assert "rows=2" in norm["out"]


def test_a_step_that_changed_nothing_is_distinct_from_a_skipped_step(tmp_path: Path):
    """A no-op run of a step still logs; a step that never ran logs nothing."""
    src = tmp_path / "clones.tsv"
    src.write_text(
        "sequence_id\tsequence_alignment\ns1\tACGT\n", encoding="utf-8"
    )

    prepared = prepare_input_for_method(
        "dowser", src, params={}, work_dir=tmp_path / "w"
    )

    # Sanitization ran and changed nothing: it still reports its no-op outcome.
    norm = _entry(prepared.log_entries, "normalize_table_delimiter")
    assert norm is not None
    assert "(unchanged)" in norm["out"]
    assert "blank rows dropped=0" in norm["out"]
    assert "byte-order mark stripped=no" in norm["out"]

    # Column mapping was not requested, so it emits no entry at all, and the
    # summary is what makes that absence unambiguous.
    assert _entry(prepared.log_entries, "rename_table_columns") is None
    summary = _entry(prepared.log_entries, "summary")
    assert summary is not None
    assert "steps applied=1" in summary["out"]
    assert "rename_table_columns" not in summary["out"]
    assert "no format conversion required" in summary["out"]


def test_warnings_are_not_converted_into_logs(tmp_path: Path):
    """Blank-row dropping stays a warning as well as being logged."""
    src = tmp_path / "excel.csv"
    src.write_bytes(b"sequence_id;sequence_alignment\ns1;ACGT\n;\n")

    prepared = prepare_input_for_method(
        "clonaltree", src, params={}, work_dir=tmp_path / "w"
    )

    assert [w["code"] for w in prepared.warnings] == ["BLANK_ROWS_DROPPED"]
    # ...and no warning leaked into the log stream as a failed step.
    assert all(e["ok"] for e in prepared.log_entries)


def test_a_steps_own_warnings_are_traceable_from_its_log_entry(tmp_path: Path):
    """Unexpected alignment characters warn AND appear against the step.

    'R' is a valid IUPAC ambiguity code, so framework validation accepts it,
    but it falls outside the narrower set GCtree's FASTA export recognises —
    which is exactly the warn-not-fail case this test is about. A character
    that is invalid outright (Z, X, a digit) is now rejected before dispatch.
    """
    src = tmp_path / "aligned.tsv"
    src.write_text(
        "sequence_id\tsequence_alignment\ns1\tACGTRRRR\ns2\tACGTACGA\n",
        encoding="utf-8",
    )

    prepared = prepare_input_for_method(
        "gctree", src, params={}, work_dir=tmp_path / "w"
    )

    # The warning is still a warning — the list is not emptied into the logs.
    assert [w["code"] for w in prepared.warnings] == ["UNEXPECTED_ALIGNMENT_CHARACTER"]
    # ...and the step that raised it says so, so the log is self-contained.
    convert = _entry(prepared.log_entries, "convert_table_to_aligned_fasta")
    assert "warnings=1" in convert["out"]
    assert convert["ok"] is True


def test_adapter_preserves_a_preexisting_logs_array():
    """The result adapter must not strip or rebuild `logs`."""
    raw = {
        "ok": True,
        "trees": [],
        "logs": [{"step": "method.build", "ok": True, "out": "done"}],
    }

    unified, _rows = assemble_unified_tree_result("gctree", raw)

    assert unified["logs"] == raw["logs"]


def test_merge_reattaches_preprocess_entries_ahead_of_service_logs():
    stored = type(
        "R",
        (),
        {
            "result": {
                "logs": [
                    {"step": "preprocess.summary", "ok": True, "out": "steps applied=1"}
                ]
            }
        },
    )()
    unified = {"ok": True, "logs": [{"step": "method.build", "ok": True, "out": "x"}]}

    merged = _merge_preprocess_logs(unified, stored)

    assert _steps(merged["logs"]) == ["preprocess.summary", "method.build"]
    # The caller's dict is not mutated in place.
    assert _steps(unified["logs"]) == ["method.build"]


def test_merge_is_a_no_op_for_runs_created_before_this_change():
    """Older runs have no preprocess entries; they must not error."""
    legacy = type("R", (), {"result": {"ok": True}})()
    unified = {"ok": True, "logs": [{"step": "method.build", "ok": True, "out": "x"}]}

    assert _merge_preprocess_logs(unified, legacy) == unified
    assert _merge_preprocess_logs(unified, None) == unified
    assert _merge_preprocess_logs({"ok": True}, legacy) == {"ok": True}


# --------------------------------------------------------------------------
# Live Postgres round-trip (see conftest.py). These prove the entries survive
# in the existing `runs.result` JSONB column with no schema change.
# --------------------------------------------------------------------------


async def _make_user(session) -> User:
    suffix = uuid.uuid4().hex[:8]
    user = User(
        id=uuid.uuid4(),
        email=f"prep-{suffix}@test.io",
        username=f"prep-{suffix}",
        password_hash="x",
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@pytest.mark.asyncio
async def test_preprocess_entries_persist_and_survive_completion(session, tmp_path):
    """Staging writes the trace; set_result must not lose it at completion."""
    src = tmp_path / "clones.tsv"
    src.write_text(
        "seqID\tcloneID\tseqAlign\tgermAlign\tvcall\tjcall\tjunclen\n"
        "a1\tc1\tACGT\tACGT\tIGHV1\tIGHJ1\t12\n",
        encoding="utf-8",
    )
    prepared = prepare_input_for_method(
        "dowser",
        src,
        params={"doMapping": True, "column_map": DOWSER_MAP},
        work_dir=tmp_path / "w",
    )

    repo = RunRepository(session)
    user = await _make_user(session)
    run = await repo.create_run(method_id="dowser", params={}, user_id=user.id)

    # 1) Staging persists the trace while the run is still active.
    await repo.append_result_logs(run.id, prepared.log_entries)
    await session.commit()

    stored = await repo.get_by_id(run.id)
    assert _steps(stored.result["logs"]) == _steps(prepared.log_entries)

    # 2) The service responds; the worker merges before overwriting `result`.
    unified, _rows = assemble_unified_tree_result(
        "dowser",
        {
            "ok": True,
            "trees": ["(a1:0.1,a2:0.1);"],
            "logs": [{"step": "dowser.buildTrees", "ok": True, "out": "built 1 tree"}],
        },
    )
    merged = _merge_preprocess_logs(unified, stored)
    await repo.set_result(run.id, merged, RunStatus.DONE)
    await session.commit()

    # 3) Read back from Postgres: preprocessing first, then the service's own.
    final = await repo.get_by_id(run.id)
    assert final.status == RunStatus.DONE
    steps = _steps(final.result["logs"])
    assert steps == [
        "preprocess.normalize_table_delimiter",
        "preprocess.validate_input_table",
        "preprocess.rename_table_columns",
        "preprocess.summary",
        "dowser.buildTrees",
    ]
    rename = _entry(final.result["logs"], "rename_table_columns")
    assert "seqID->sequence_id" in rename["out"]


@pytest.mark.asyncio
async def test_append_result_logs_ignores_terminal_runs_and_empty_input(session):
    repo = RunRepository(session)
    user = await _make_user(session)
    run = await repo.create_run(method_id="dowser", params={}, user_id=user.id)

    assert await repo.append_result_logs(run.id, []) is None

    await repo.set_result(run.id, {"ok": True}, RunStatus.DONE)
    await session.commit()

    # A finished run must not have its stored result rewritten.
    entry = [{"step": "preprocess.summary", "ok": True, "out": "late"}]
    assert await repo.append_result_logs(run.id, entry) is None
    final = await repo.get_by_id(run.id)
    assert "logs" not in final.result
