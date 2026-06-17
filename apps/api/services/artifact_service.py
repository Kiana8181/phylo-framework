"""Artifact ingest: turn a method service's manifest into DB rows.

Method services upload their artifact files (PNGs, ZIPs, logs, etc.) directly
to MinIO using a scoped PutObject-only user, then declare each upload in
``result.json`` under ``artifacts`` (the manifest). This service:

  - validates the manifest version,
  - classifies each entry's kind / previewability / content-type (manifest
    values win over filename extension),
  - normalizes the row shape ArtifactRepository expects.

No file I/O happens here. The worker does NOT access the method's filesystem,
does NOT upload to object storage, and never sees the artifact bytes. The
upload contract is enforced by the scoped MinIO user (see ``minio-init`` in
docker-compose.yml).
"""
from __future__ import annotations

import mimetypes
import os
import re
import uuid
from typing import Any, Iterable

from apps.api.database.models import ArtifactKind

# Manifest schema version(s) this worker understands. Bump additively.
SUPPORTED_MANIFEST_VERSIONS = {1}

_EXT_KIND: dict[str, ArtifactKind] = {
    ".png": ArtifactKind.IMAGE,
    ".jpg": ArtifactKind.IMAGE,
    ".jpeg": ArtifactKind.IMAGE,
    ".gif": ArtifactKind.IMAGE,
    ".webp": ArtifactKind.IMAGE,
    ".svg": ArtifactKind.IMAGE,
    ".pdf": ArtifactKind.IMAGE,
    ".nwk": ArtifactKind.NEWICK,
    ".newick": ArtifactKind.NEWICK,
    ".tree": ArtifactKind.NEWICK,
    ".tsv": ArtifactKind.TABLE,
    ".csv": ArtifactKind.TABLE,
    ".fasta": ArtifactKind.FASTA,
    ".fa": ArtifactKind.FASTA,
    ".fas": ArtifactKind.FASTA,
    ".json": ArtifactKind.JSON,
    ".log": ArtifactKind.LOG,
    ".txt": ArtifactKind.LOG,
    ".zip": ArtifactKind.ZIP,
}

_PREVIEWABLE_KINDS = {
    ArtifactKind.IMAGE,
    ArtifactKind.NEWICK,
    ArtifactKind.TABLE,
    ArtifactKind.FASTA,
    ArtifactKind.JSON,
    ArtifactKind.LOG,
}

_CONTENT_TYPE_OVERRIDES = {
    ".svg": "image/svg+xml",
    ".nwk": "text/plain",
    ".newick": "text/plain",
    ".tree": "text/plain",
    ".tsv": "text/tab-separated-values",
    ".fasta": "text/plain",
    ".fa": "text/plain",
    ".fas": "text/plain",
    ".log": "text/plain",
}


class ManifestError(Exception):
    """Raised when a method-service manifest is missing or has an unknown version."""


def secure_filename(name: str) -> str:
    """Return a safe basename: strip directories and unsafe characters."""
    base = os.path.basename((name or "").strip().replace("\\", "/"))
    base = base.lstrip(".") or "artifact"
    base = re.sub(r"[^A-Za-z0-9._-]+", "_", base)
    return base[:200] or "artifact"


def _classify(filename: str) -> tuple[ArtifactKind, str | None, bool]:
    ext = os.path.splitext(filename)[1].lower()
    kind = _EXT_KIND.get(ext, ArtifactKind.OTHER)
    content_type = _CONTENT_TYPE_OVERRIDES.get(ext) or mimetypes.guess_type(filename)[0]
    previewable = kind in _PREVIEWABLE_KINDS
    return kind, content_type, previewable


def tree_id_for_index(method_id: str, index: int) -> str:
    """Match the tree id scheme used by tree_contract.assemble_unified_tree_result."""
    return f"{method_id}-tree-{index + 1}"


def parse_manifest(result: dict[str, Any]) -> list[dict[str, Any]]:
    """Validate and return the artifact list from a method result payload.

    Raises ManifestError if the manifest is absent or its version is unknown.
    """
    if not isinstance(result, dict):
        raise ManifestError("Method result is not a JSON object.")
    version = result.get("manifest_version")
    if version is None:
        raise ManifestError(
            "Method result is missing 'manifest_version'. The method service must "
            "emit a file manifest (base64 results are no longer supported)."
        )
    try:
        version_int = int(version)
    except (TypeError, ValueError):
        raise ManifestError(f"Invalid manifest_version: {version!r}")
    if version_int not in SUPPORTED_MANIFEST_VERSIONS:
        raise ManifestError(
            f"Unsupported manifest_version {version_int}; this worker supports "
            f"{sorted(SUPPORTED_MANIFEST_VERSIONS)}."
        )
    artifacts = result.get("artifacts")
    if artifacts is None:
        return []
    if not isinstance(artifacts, list):
        raise ManifestError("Manifest 'artifacts' must be a list.")
    return [a for a in artifacts if isinstance(a, dict)]


class ArtifactService:
    """Translates a method's manifest into ArtifactRepository row dicts."""

    def __init__(self, bucket: str | None = None):
        # Bucket name is informational on the row (handy for the download API
        # which builds object URLs). It comes from env so we don't have to
        # carry a storage client around.
        self.bucket = bucket or os.environ.get("S3_BUCKET_ARTIFACTS", "phylo-artifacts")
        self.backend = (os.environ.get("STORAGE_BACKEND") or "minio").strip().lower() or "minio"

    def ingest(
        self,
        *,
        run_id: uuid.UUID,
        method_id: str,
        manifest_artifacts: Iterable[dict[str, Any]],
        logs_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Build ArtifactRepository row dicts from manifest entries.

        Each manifest entry must carry ``object_key`` (already in the artifact
        bucket), ``filename``, ``size_bytes``, ``checksum_sha256``. Optional
        fields: ``kind``, ``role``, ``content_type``, ``previewable``,
        ``tree_index``, ``tree_id``.
        """
        rows: list[dict[str, Any]] = []

        for entry in manifest_artifacts:
            object_key = str(entry.get("object_key") or "").strip()
            if not object_key:
                continue

            filename = secure_filename(
                str(entry.get("filename") or os.path.basename(object_key))
            )
            kind_raw = entry.get("kind")
            kind, content_type, previewable = _classify(filename)
            if isinstance(kind_raw, str) and kind_raw.strip():
                try:
                    kind = ArtifactKind(kind_raw.strip().lower())
                    previewable = kind in _PREVIEWABLE_KINDS
                except ValueError:
                    pass
            if isinstance(entry.get("content_type"), str) and entry["content_type"].strip():
                content_type = entry["content_type"].strip()
            if "previewable" in entry:
                previewable = bool(entry["previewable"])

            if logs_only and kind != ArtifactKind.LOG:
                continue

            tree_id = None
            if entry.get("tree_id"):
                tree_id = str(entry["tree_id"])
            elif entry.get("tree_index") is not None:
                try:
                    tree_id = tree_id_for_index(method_id, int(entry["tree_index"]))
                except (TypeError, ValueError):
                    tree_id = None

            try:
                size_bytes = int(entry.get("size_bytes") or 0)
            except (TypeError, ValueError):
                size_bytes = 0
            checksum = str(entry.get("checksum_sha256") or "").strip().lower()

            rows.append(
                {
                    "id": uuid.uuid4(),
                    "tree_id": tree_id,
                    "storage_backend": self.backend,
                    "storage_bucket": self.bucket,
                    "object_key": object_key,
                    "filename": filename,
                    "content_type": content_type,
                    "size_bytes": size_bytes,
                    "checksum_sha256": checksum or None,
                    "artifact_kind": kind,
                    "artifact_role": (str(entry["role"]).strip() if entry.get("role") else None),
                    "is_previewable": previewable,
                }
            )
        return rows
