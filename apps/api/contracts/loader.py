from __future__ import annotations
from pathlib import Path
from typing import Any, Dict, List, Optional
import json

from apps.api.config import CONTRACTS_DIR

METHODS_DIR = CONTRACTS_DIR / "methods"

def _read_json(p: Path) -> Any:
    with p.open("r", encoding="utf-8") as f:
        return json.load(f)

_METHOD_INFO_OPTIONAL_FIELDS = (
    "tagline",
    "category",
    "summary",
    "capabilities",
    "inputFormats",
    "externalDocUrl",
    "externalDocLabel",
)


def list_methods_from_contracts() -> List[Dict[str, Any]]:
    """
    Build MethodInfo[] by scanning packages/contracts/methods/* directories.
    If spec.json exists, use its name/version. Otherwise infer reasonable defaults.
    """
    infos: List[Dict[str, Any]] = []
    if not METHODS_DIR.exists():
        return infos

    for d in sorted(METHODS_DIR.iterdir()):
        if not d.is_dir():
            continue
        method_id = d.name
        name = method_id.capitalize()
        version = "0.1.0"
        extras: Dict[str, Any] = {}

        spec_json = d / "spec.json"
        if spec_json.exists():
            try:
                spec = _read_json(spec_json)
                name = spec.get("name", name)
                version = spec.get("version", version)
                for key in _METHOD_INFO_OPTIONAL_FIELDS:
                    if key in spec and spec[key] is not None:
                        extras[key] = spec[key]
            except Exception:
                # Do not crash—fallback to inferred
                pass

        infos.append({"id": method_id, "name": name, "version": version, **extras})
    return infos

def get_param_schema(method_id: str) -> Dict[str, Any] | None:
    p = METHODS_DIR / method_id / "param.schema.json"
    return _read_json(p) if p.exists() else None

def get_result_schema(method_id: str) -> Dict[str, Any] | None:
    p = METHODS_DIR / method_id / "result.schema.json"
    return _read_json(p) if p.exists() else None

def get_ui_hints(method_id: str) -> Dict[str, Any]:
    """
    Optional ui.json next to schemas. Fallback to simple defaults.
    """
    ui = METHODS_DIR / method_id / "ui.json"
    if ui.exists():
        try:
            return _read_json(ui)
        except Exception:
            pass
    return {"requiresFile": True, "maxFiles": 1}

def get_accepts(method_id: str) -> List[str]:
    """
    If spec.json has 'accepts', use it. Otherwise provide a sane union
    of plausible file types for phylo pipelines.
    """
    spec_json = METHODS_DIR / method_id / "spec.json"
    if spec_json.exists():
        try:
            spec = _read_json(spec_json)
            accepts = spec.get("accepts")
            if isinstance(accepts, list) and accepts:
                return accepts
        except Exception:
            pass
    return [
        "text/csv",
        "text/tab-separated-values",
        "application/x-rds",
        "application/x-rda",
        "text/fasta",
        "application/octet-stream",
    ]

def load_spec_from_contracts(method_id: str) -> Dict[str, Any]:
    """
    Build a MethodSpec-like dict from contracts only (no network).
    """
    param_schema = get_param_schema(method_id) or {"type": "object", "properties": {}, "required": []}
    ui_hints = get_ui_hints(method_id)
    accepts = get_accepts(method_id)

    # name/version via the same logic as list_methods
    name, version = method_id.capitalize(), "0.1.0"
    spec_json = METHODS_DIR / method_id / "spec.json"
    if spec_json.exists():
        try:
            spec = _read_json(spec_json)
            name = spec.get("name", name)
            version = spec.get("version", version)
        except Exception:
            pass

    return {
        "id": method_id,
        "name": name,
        "version": version,
        "accepts": accepts,
        "paramSchema": param_schema,
        "uiHints": ui_hints,
    }


_DEFAULT_SERVICE_ROUTES = {
    "spec": "/spec",
    "run": "/run",
    "jobs": "/jobs",
    "jobStatus": "/jobs/{job_id}/status",
    "jobResult": "/jobs/{job_id}/result",
    "jobCancel": "/jobs/{job_id}/cancel",
    "capacity": "/capacity",
}


def get_service_routes(method_id: str) -> dict:
    p = METHODS_DIR / method_id / "service.routes.json"
    routes = dict(_DEFAULT_SERVICE_ROUTES)
    if p.exists():
        d = _read_json(p)
        for key in routes:
            if isinstance(d.get(key), str) and d[key].strip():
                routes[key] = d[key]
    return routes
