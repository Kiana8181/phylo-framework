"""Runtime access to the deployment's version-information file.

`scripts/generate-version-info.mjs` writes `runtime/version-info.json` at build
or deploy time; this module reads it once and hands the contents to the worker,
which stores a copy in each run's result under `version_info`. Recording it per
run means a stored result stays interpretable even after the deployment behind
it has been rebuilt.

Capture must never fail a run. Every entry point here returns `None` rather than
raising, so a missing or damaged file costs provenance and nothing else. Runs
recorded before this feature simply have no `version_info` key.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from apps.api.config import ROOT_DIR

DEFAULT_VERSION_INFO_PATH = ROOT_DIR / "runtime" / "version-info.json"

# Populated on first read. `False` is the "we looked and found nothing" marker,
# which lets a missing file stay cached instead of being re-stat'd per run.
_cache: dict[str, Any] | None | bool = False


def version_info_path() -> Path:
    """Resolve the capture file, honouring `PHYLO_VERSION_INFO_PATH`."""
    override = os.getenv("PHYLO_VERSION_INFO_PATH", "").strip()
    if not override:
        return DEFAULT_VERSION_INFO_PATH
    path = Path(override)
    return path if path.is_absolute() else (ROOT_DIR / path)


def load_version_info(*, refresh: bool = False) -> dict[str, Any] | None:
    """Return the captured version info, or `None` if it is unusable.

    `None` covers every failure mode — absent file, unreadable file, malformed
    JSON, or a JSON document that is not an object. The distinction does not
    matter to callers, all of which degrade the same way.
    """
    global _cache
    if not refresh and _cache is not False:
        return _cache  # type: ignore[return-value]

    path = version_info_path()
    try:
        with path.open(encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        _cache = None
        return None
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        # Present but damaged. Same outcome as absent, but worth distinguishing
        # in the log so a broken deploy step is visible.
        _cache = None
        return None

    _cache = payload if isinstance(payload, dict) else None
    return _cache  # type: ignore[return-value]


def build_run_version_info(
    method_id: str,
    service_provenance: Any = None,
) -> dict[str, Any] | None:
    """Assemble the `version_info` block stored on a single run.

    Narrows the deployment-wide capture to the one service that ran, and folds
    in whatever that service reported about itself at run time (ClonalTree, for
    example, already returns its submodule commit and MUSCLE version). Returns
    `None` when there is nothing worth storing.
    """
    captured = load_version_info()

    service_reported = service_provenance if isinstance(service_provenance, dict) else None
    if captured is None and service_reported is None:
        return None

    block: dict[str, Any] = {"method_id": method_id}

    if captured is not None:
        block["schema_version"] = captured.get("schema_version")
        block["captured_at"] = captured.get("generated_at")
        block["framework"] = captured.get("framework")
        block["reference_data"] = captured.get("reference_data")

        services = captured.get("services")
        if isinstance(services, dict):
            # Only the service that actually ran; the other three say nothing
            # about this run.
            block["service"] = services.get(method_id)
        else:
            block["service"] = None

        unavailable = captured.get("unavailable")
        if isinstance(unavailable, dict):
            prefix = f"services.{method_id}."
            block["unavailable"] = {
                key: reason
                for key, reason in unavailable.items()
                if not key.startswith("services.") or key.startswith(prefix)
            }
    else:
        block["unavailable"] = {
            "*": "no version-information file was present in this deployment",
        }

    if service_reported is not None:
        # Kept separate from the build-time capture: this is what the service
        # observed about itself while running, which can differ from what the
        # build definition declared.
        block["service_reported"] = service_reported

    return block


def attach_version_info(
    unified_result: dict[str, Any],
    method_id: str,
) -> dict[str, Any]:
    """Return `unified_result` with a `version_info` block added.

    Never raises and never overwrites an existing `version_info`. On any failure
    the result is returned untouched, so a provenance problem cannot fail a run
    that otherwise succeeded.
    """
    try:
        if not isinstance(unified_result, dict) or "version_info" in unified_result:
            return unified_result
        block = build_run_version_info(method_id, unified_result.get("provenance"))
        if block is None:
            return unified_result
        merged = dict(unified_result)
        merged["version_info"] = block
        return merged
    except Exception:  # noqa: BLE001 - provenance is never worth failing a run for
        return unified_result
