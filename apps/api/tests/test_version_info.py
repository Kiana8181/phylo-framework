"""Unit tests for build-time version capture and its attachment to results.

The load path must degrade quietly: a deployment with no capture file, or a
damaged one, costs provenance and never a run. The 36 evaluation runs in
`output/` predate this feature and must keep loading, which is what the
"no version_info key" assertions below stand for.

Run from the repo root:
    .venv/bin/python -m pytest apps/api/tests/test_version_info.py
"""
import json

import pytest

from apps.api.services import version_info as vi


@pytest.fixture(autouse=True)
def _clear_cache():
    """The module caches the first read; isolate each test from the others."""
    vi._cache = False
    yield
    vi._cache = False


def _write(tmp_path, payload, monkeypatch, *, raw=None):
    path = tmp_path / "version-info.json"
    path.write_text(raw if raw is not None else json.dumps(payload), encoding="utf-8")
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(path))
    return path


FULL = {
    "schema_version": 1,
    "generated_at": "2026-08-21T18:30:03.524Z",
    "framework": {"version": "v1.9.0", "git_commit": "abc123", "git_dirty": False},
    "services": {
        "gctree": {
            "image_name": "phylo-gctree:dev",
            "image_digest": "phylo-gctree@sha256:827dce",
            "tool_versions": {"gctree": "4.3.0"},
        },
        "dowser": {"image_name": "phylo-dowser:dev"},
    },
    "reference_data": None,
    "unavailable": {
        "reference_data": "bundled in the upstream image",
        "services.dowser.tool_versions": "no pins in the build definition",
    },
}


# --------------------------------------------------------------- loading

def test_load_returns_none_when_file_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(tmp_path / "nope.json"))
    assert vi.load_version_info() is None


def test_load_returns_none_on_malformed_json(tmp_path, monkeypatch):
    _write(tmp_path, None, monkeypatch, raw="{not json")
    assert vi.load_version_info() is None


def test_load_returns_none_when_document_is_not_an_object(tmp_path, monkeypatch):
    _write(tmp_path, ["a", "list"], monkeypatch)
    assert vi.load_version_info() is None


def test_load_reads_a_well_formed_file(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    loaded = vi.load_version_info()
    assert loaded is not None
    assert loaded["framework"]["version"] == "v1.9.0"


def test_relative_override_resolves_against_repo_root(monkeypatch):
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", "runtime/version-info.json")
    assert vi.version_info_path().is_absolute()


# ------------------------------------------------------ per-run assembly

def test_block_narrows_to_the_service_that_ran(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    block = vi.build_run_version_info("gctree")
    assert block is not None
    assert block["method_id"] == "gctree"
    assert block["service"]["image_digest"] == "phylo-gctree@sha256:827dce"
    assert block["framework"]["version"] == "v1.9.0"


def test_block_drops_other_services_unavailable_notes(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    block = vi.build_run_version_info("gctree")
    # Dowser's gap says nothing about a GCtree run; the global one still does.
    assert "services.dowser.tool_versions" not in block["unavailable"]
    assert "reference_data" in block["unavailable"]


def test_block_handles_a_service_missing_from_the_capture(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    block = vi.build_run_version_info("clonaltree")
    assert block is not None
    assert block["service"] is None


def test_partial_capture_file_does_not_raise(tmp_path, monkeypatch):
    _write(tmp_path, {"schema_version": 1}, monkeypatch)
    block = vi.build_run_version_info("gctree")
    assert block is not None
    assert block["framework"] is None
    assert block["service"] is None


def test_service_reported_provenance_is_folded_in(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    reported = {"muscle": {"major": 5}, "container": {"image_digest": None}}
    block = vi.build_run_version_info("clonaltree", reported)
    assert block["service_reported"] == reported


def test_service_provenance_alone_still_produces_a_block(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(tmp_path / "absent.json"))
    block = vi.build_run_version_info("clonaltree", {"muscle": {"major": 5}})
    assert block is not None
    assert block["service_reported"] == {"muscle": {"major": 5}}
    assert block["unavailable"]["*"]


def test_no_capture_and_no_service_provenance_yields_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(tmp_path / "absent.json"))
    assert vi.build_run_version_info("gctree") is None


def test_non_dict_service_provenance_is_ignored(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    block = vi.build_run_version_info("gctree", "not-a-dict")
    assert "service_reported" not in block


# ------------------------------------------------------------ attachment

def test_attach_adds_the_block_to_a_result(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    result = vi.attach_version_info({"ok": True, "trees": []}, "gctree")
    assert result["version_info"]["method_id"] == "gctree"
    # Additive only.
    assert result["ok"] is True and result["trees"] == []


def test_attach_uses_the_results_own_provenance_block(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    result = vi.attach_version_info(
        {"ok": True, "trees": [], "provenance": {"muscle": {"major": 5}}}, "clonaltree"
    )
    assert result["version_info"]["service_reported"] == {"muscle": {"major": 5}}
    # The original key is left where it was.
    assert result["provenance"] == {"muscle": {"major": 5}}


def test_attach_is_a_noop_without_a_capture_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PHYLO_VERSION_INFO_PATH", str(tmp_path / "absent.json"))
    result = vi.attach_version_info({"ok": True, "trees": []}, "gctree")
    assert "version_info" not in result


def test_attach_never_overwrites_an_existing_block(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    result = vi.attach_version_info(
        {"ok": True, "trees": [], "version_info": {"method_id": "kept"}}, "gctree"
    )
    assert result["version_info"] == {"method_id": "kept"}


def test_attach_tolerates_a_non_dict_result(tmp_path, monkeypatch):
    _write(tmp_path, FULL, monkeypatch)
    assert vi.attach_version_info(None, "gctree") is None  # type: ignore[arg-type]


def test_attach_survives_an_exploding_loader(tmp_path, monkeypatch):
    """Provenance capture must never be the reason a finished run fails."""
    def boom(*_args, **_kwargs):
        raise RuntimeError("capture backend on fire")

    monkeypatch.setattr(vi, "build_run_version_info", boom)
    result = vi.attach_version_info({"ok": True, "trees": []}, "gctree")
    assert result == {"ok": True, "trees": []}
