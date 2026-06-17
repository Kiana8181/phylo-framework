"""Unit tests for artifact ingest + manifest handling and base64-free results.

Run: STORAGE_BACKEND=minio python -m pytest apps/api/tests/test_artifact_manifest.py
(no MinIO connection is made — these tests are pure unit tests.)
"""
from __future__ import annotations

import json
import os
import uuid

import pytest

os.environ.setdefault("STORAGE_BACKEND", "minio")
os.environ.setdefault("S3_BUCKET_ARTIFACTS", "phylo-artifacts")

from apps.api.services.artifact_service import (  # noqa: E402
    ArtifactService,
    ManifestError,
    parse_manifest,
    secure_filename,
    tree_id_for_index,
)
from apps.api.services.tree_contract import assemble_unified_tree_result  # noqa: E402


def test_parse_manifest_requires_known_version():
    assert parse_manifest({"manifest_version": 1, "artifacts": []}) == []
    with pytest.raises(ManifestError):
        parse_manifest({})  # missing version
    with pytest.raises(ManifestError):
        parse_manifest({"manifest_version": 2})  # unsupported
    with pytest.raises(ManifestError):
        parse_manifest({"manifest_version": "x"})  # invalid


def test_secure_filename_sanitizes():
    assert secure_filename("../../etc/passwd") == "passwd"
    assert secure_filename("a b/c?.png") == "c_.png"
    assert secure_filename("") == "artifact"


def test_tree_id_scheme_matches_contract():
    assert tree_id_for_index("gctree", 0) == "gctree-tree-1"
    assert tree_id_for_index("dowser", 4) == "dowser-tree-5"


def test_ingest_builds_rows_from_manifest():
    """Methods upload directly to MinIO and emit object keys + checksums; the
    worker never touches the bytes, so ingest is a pure manifest -> row
    transformation."""
    run_id = uuid.uuid4()
    job_id = "test-job-1"
    manifest = [
        {
            "object_key": f"artifacts/{run_id}/{job_id}/tree_plot_01.png",
            "filename": "tree_plot_01.png",
            "size_bytes": 9,
            "checksum_sha256": "a" * 64,
            "kind": "image",
            "role": "phylogeny",
            "tree_index": 0,
            "content_type": "image/png",
            "previewable": True,
        },
        {
            "object_key": f"artifacts/{run_id}/{job_id}/bundle.zip",
            "filename": "bundle.zip",
            "size_bytes": 5,
            "checksum_sha256": "b" * 64,
            "kind": "zip",
            "role": "bundle",
        },
        {
            # Missing object_key => skipped.
            "filename": "no_key.txt",
            "size_bytes": 1,
            "checksum_sha256": "c" * 64,
        },
    ]
    svc = ArtifactService(bucket="phylo-artifacts")
    rows = svc.ingest(run_id=run_id, method_id="gctree", manifest_artifacts=manifest)
    assert len(rows) == 2  # entry without object_key skipped
    png = next(r for r in rows if r["filename"] == "tree_plot_01.png")
    assert png["tree_id"] == "gctree-tree-1"
    assert png["is_previewable"] is True
    assert png["checksum_sha256"] == "a" * 64
    assert png["size_bytes"] == 9
    assert png["object_key"].startswith("artifacts/")
    assert png["storage_bucket"] == "phylo-artifacts"


def test_ingest_logs_only_filters_to_log_kind():
    """The failure path uses logs_only=True to extract just the job.log
    entry the method auto-uploaded."""
    run_id = uuid.uuid4()
    job_id = "test-job-2"
    manifest = [
        {
            "object_key": f"artifacts/{run_id}/{job_id}/phylogeny_1.png",
            "filename": "phylogeny_1.png",
            "size_bytes": 100,
            "checksum_sha256": "d" * 64,
            "kind": "image",
            "role": "phylogeny",
        },
        {
            "object_key": f"artifacts/{run_id}/{job_id}/job.log",
            "filename": "job.log",
            "size_bytes": 200,
            "checksum_sha256": "e" * 64,
            "kind": "log",
            "role": "log",
        },
    ]
    svc = ArtifactService(bucket="phylo-artifacts")
    rows = svc.ingest(
        run_id=run_id, method_id="dowser", manifest_artifacts=manifest, logs_only=True
    )
    assert len(rows) == 1
    assert rows[0]["filename"] == "job.log"


def test_assemble_result_strips_all_base64():
    raw = {
        "ok": True,
        "trees": ["(A:1,B:1);"],
        "clones": {"clone_id": ["c1"]},
        "stats": {"n": 2},
        "figures": {"phylogeny": ["data:image/png;base64,AAAA"]},
        "artifact_zip_b64": "UEsDBBQ=",
        "artifact_name": "bundle.zip",
        "visualizations": {"service_image": {"mime": "image/png", "base64": "ZZZ"}},
        "manifest_version": 1,
        "artifacts": [{"object_key": "artifacts/x.png"}],
    }
    unified, rows = assemble_unified_tree_result("gctree", raw)
    blob = json.dumps(unified)
    assert "base64" not in blob and "data:" not in blob
    for k in ("figures", "artifact_zip_b64", "artifact_name", "visualizations", "artifacts", "manifest_version"):
        assert k not in unified
    assert unified["stats"] == {"n": 2}
    assert rows and "service_image" not in rows[0]
