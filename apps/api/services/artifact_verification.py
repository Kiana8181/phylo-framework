"""Check that a run's artifacts really are in the object store.

Method services upload their artifacts themselves and only tell the worker what
they uploaded (the manifest). A run must not be reported as finished on the
strength of that claim alone: before a run becomes ``DONE`` the worker asks the
store for every declared object and compares what it finds with the manifest.

Checked per artifact:
  - the object exists;
  - its size equals the declared ``size_bytes``;
  - when the uploader recorded a SHA-256 on the object and the manifest declares
    one, the two match. (The method services stamp it at upload. This compares
    the two declarations; it does not re-read the object's bytes.)

"The store did not answer" is a different outcome from "the object is missing":
the first is retried a bounded number of times and then reported as the store
being unavailable.

Settings: ARTIFACT_VERIFY_ATTEMPTS (default 3), ARTIFACT_VERIFY_RETRY_SECONDS
(default 5) and ARTIFACT_VERIFY_TIMEOUT_SECONDS (default 30, per object).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Iterable

from apps.api.storage.base import StorageInterface


def _int_env(name: str, default: int, minimum: int) -> int:
    try:
        return max(minimum, int(float(os.getenv(name, "") or default)))
    except ValueError:
        return default


def verify_attempts() -> int:
    return _int_env("ARTIFACT_VERIFY_ATTEMPTS", 3, 1)


def verify_retry_seconds() -> float:
    try:
        return max(0.0, float(os.getenv("ARTIFACT_VERIFY_RETRY_SECONDS", "") or 5))
    except ValueError:
        return 5.0


def verify_timeout_seconds() -> float:
    """Longest one question to the store may take before it counts as unanswered."""
    try:
        return max(1.0, float(os.getenv("ARTIFACT_VERIFY_TIMEOUT_SECONDS", "") or 30))
    except ValueError:
        return 30.0


class ArtifactStoreUnavailable(Exception):
    """The object store could not be asked (after the configured retries)."""


@dataclass
class VerificationReport:
    checked: int = 0
    # One entry per artifact that is not stored as declared.
    problems: list[dict[str, Any]] = field(default_factory=list)
    # object_key of every artifact that is stored as declared.
    verified_keys: set[str] = field(default_factory=set)

    @property
    def ok(self) -> bool:
        return not self.problems

    def summary(self, limit: int = 5) -> str:
        """Short description for a message: file names, then what is wrong."""
        shown = self.problems[:limit]
        more = len(self.problems) - len(shown)
        tail = f", and {more} more" if more > 0 else ""
        kinds = {p["problem"] for p in self.problems}
        if len(kinds) == 1:
            return f"{', '.join(p['filename'] for p in shown)}{tail}: {kinds.pop()}"
        return ", ".join(f"{p['filename']} ({p['problem']})" for p in shown) + tail


async def _verify_once(rows: list[dict[str, Any]], storage: StorageInterface) -> VerificationReport:
    report = VerificationReport()
    per_object_timeout = verify_timeout_seconds()
    for row in rows:
        key = str(row.get("object_key") or "")
        filename = str(row.get("filename") or key)
        declared_size = int(row.get("size_bytes") or 0)
        declared_sha = str(row.get("checksum_sha256") or "").strip().lower()
        # A store that accepts the connection but never answers must not hold
        # the run open: treat silence as "unavailable" like any other failure.
        stat = await asyncio.wait_for(storage.stat(key), timeout=per_object_timeout)
        report.checked += 1
        if stat is None:
            report.problems.append({"filename": filename, "object_key": key, "problem": "not in the object store"})
            continue
        if stat.size_bytes != declared_size:
            report.problems.append({
                "filename": filename, "object_key": key,
                "problem": f"stored size {stat.size_bytes} bytes, expected {declared_size}",
            })
            continue
        if stat.sha256 and declared_sha and stat.sha256 != declared_sha:
            report.problems.append({"filename": filename, "object_key": key, "problem": "checksum differs"})
            continue
        report.verified_keys.add(key)
    return report


async def verify_artifacts(
    rows: Iterable[dict[str, Any]],
    storage: StorageInterface,
    *,
    attempts: int | None = None,
    retry_seconds: float | None = None,
) -> VerificationReport:
    """Compare artifact rows with the store. Raises ArtifactStoreUnavailable
    when the store cannot be asked; otherwise returns the report."""
    rows = list(rows)
    attempts = verify_attempts() if attempts is None else max(1, attempts)
    retry_seconds = verify_retry_seconds() if retry_seconds is None else retry_seconds
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await _verify_once(rows, storage)
        except Exception as exc:  # noqa: BLE001 - any store/network fault
            last_error = exc
            if attempt < attempts:
                await asyncio.sleep(retry_seconds)
    raise ArtifactStoreUnavailable(
        f"object store did not answer after {attempts} attempt(s)"
    ) from last_error
