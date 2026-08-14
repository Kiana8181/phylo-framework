# services/clonaltree/app.py
from __future__ import annotations

import base64
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from fastapi import FastAPI, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from validators import validate_clonaltree_input

load_dotenv()

# ---------- constants ----------
METHOD_ID = "clonaltree"
ROOT_DIR = Path(__file__).resolve().parent
BASE_CODES_DIR = ROOT_DIR / "base-codes"

CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", "/contracts"))
METHOD_DIR = CONTRACTS_DIR / "methods" / METHOD_ID


def _read_json(p: Path, default=None):
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


PARAM_SCHEMA_PATH = METHOD_DIR / "param.schema.json"
SPEC_JSON_PATH = METHOD_DIR / "spec.json"
UI_JSON_PATH = METHOD_DIR / "ui.json"
ROUTES_JSON_PATH = METHOD_DIR / "service.routes.json"

SPEC_JSON = _read_json(SPEC_JSON_PATH, {})
UI_JSON = _read_json(UI_JSON_PATH, {})
_DEFAULT_ROUTES = {
    "spec": "/spec",
    "run": "/run",
    "jobs": "/jobs",
    "jobStatus": "/jobs/{job_id}/status",
    "jobResult": "/jobs/{job_id}/result",
    "jobCancel": "/jobs/{job_id}/cancel",
}
ROUTES = {**_DEFAULT_ROUTES, **(_read_json(ROUTES_JSON_PATH, {}) or {})}
STRICT_CONTRACT_ROUTES = os.environ.get("STRICT_CONTRACT_ROUTES", "true").lower() in (
    "1",
    "true",
    "yes",
)

DEFAULT_ACCEPTS = [
    "text/tab-separated-values",
    "text/plain",
    "text/csv",
    "application/octet-stream",
]
DEFAULT_UI = {"requiresFile": True, "maxFiles": 1}

# Headless env for child procs
DEFAULT_ENV = {
    "QT_QPA_PLATFORM": "offscreen",
    "MPLBACKEND": "agg",
    "LC_ALL": "C",
    "LANG": "C",
}

REPERTOIRE_TABLE_COLUMNS = [
    "clone_label",
    "clone_id",
    "abundance",
    "sequence_count",
    "clonotype_profile",
    "v_call",
    "j_call",
    "clonotype_members",
]


# ---------- FastAPI ----------
app = FastAPI(title="ClonalTree microservice (bridge)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def ok(data, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=data)


def err(
    msg,
    status_code: int = 400,
    logs: Optional[List[dict]] = None,
    details: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    payload: Dict[str, Any] = {"ok": False, "error": msg}
    if logs:
        payload["logs"] = logs
    if details:
        payload["error_details"] = details
    return JSONResponse(status_code=status_code, content=payload)


# ---------- helpers ----------
def _env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(DEFAULT_ENV)
    if extra:
        env.update(extra)
    return env


def run_capture(
    cmd: List[str],
    cwd: Path,
    step: str,
    logs: List[dict],
    extra_env: Optional[Dict[str, str]] = None,
) -> bool:
    """
    Run a command, capture combined stdout/stderr, append to logs.
    Returns True if exit code == 0.
    """
    try:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=_env(extra_env),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        out, _ = p.communicate()
        ok_flag = p.returncode == 0
    except Exception as e:
        out = f"failed to spawn: {e}"
        ok_flag = False

    logs.append({"step": step, "cmd": " ".join(cmd), "ok": ok_flag, "out": out})
    return ok_flag


def slugify(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", name.strip())
    return cleaned or "clonaltree_run"


def parse_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "y", "on"}:
        return True
    if text in {"0", "false", "no", "n", "off"}:
        return False
    return default


def parse_clonotype_limits(raw: str) -> List[str | int]:
    if not raw:
        return []
    vals: List[str | int] = []
    seen: set[str] = set()
    for tok in re.split(r"[,\s]+", raw.strip()):
        if not tok:
            continue
        lower = tok.lower()
        if lower == "all":
            if "all" not in seen:
                vals.append("all")
                seen.add("all")
            continue
        try:
            v = int(tok)
            if v > 0:
                key = str(v)
                if key not in seen:
                    vals.append(v)
                    seen.add(key)
        except Exception:
            continue
    return vals


def muscle_major_version() -> Tuple[Optional[int], str]:
    try:
        p = subprocess.run(
            ["muscle", "-version"],
            env=_env(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        out = (p.stdout or "").strip()
    except Exception as e:
        return None, f"muscle -version failed: {e}"

    patterns = [
        r"[Vv]ersion\s*([0-9]+)",
        r"[Vv]([0-9]+)\.",
        r"muscle\s*([0-9]+)",
    ]
    for pattern in patterns:
        m = re.search(pattern, out)
        if not m:
            continue
        try:
            return int(m.group(1)), out
        except Exception:
            continue
    return None, out


def ensure_muscle_v5(logs: List[dict]) -> Tuple[bool, Optional[int], str]:
    major, raw = muscle_major_version()
    ok_flag = major is not None and major >= 5
    logs.append(
        {
            "step": "muscle_version",
            "cmd": "muscle -version",
            "ok": ok_flag,
            "out": raw,
        }
    )
    return ok_flag, major, raw


def clamp_float(val: Any, default: float, lo: float, hi: float) -> float:
    try:
        x = float(val)
    except Exception:
        return default
    if x < lo:
        return lo
    if x > hi:
        return hi
    return x


def clamp_int(val: Any, default: int, lo: int) -> int:
    try:
        x = int(val)
    except Exception:
        return default
    return max(lo, x)


def clamp_choice_int(val: Any, default: int, allowed: set[int]) -> int:
    try:
        x = int(val)
    except Exception:
        return default
    if x in allowed:
        return x
    return default


def clamp_choice_str(val: Any, default: str, allowed: set[str]) -> str:
    text = str(val).strip().upper() if val is not None else default
    if text in allowed:
        return text
    return default


def ensure_clonotype_submodule(logs: List[dict]) -> Tuple[bool, str]:
    required_paths = [
        BASE_CODES_DIR / "main_pipeline.py",
        BASE_CODES_DIR / "src/format/format_labeling_imgt_airr.py",
        BASE_CODES_DIR / "src/cluster/initial_clustering.py",
        BASE_CODES_DIR / "src/refinement/refinement.py",
        BASE_CODES_DIR / "src/cluster/two_level_clonal_info.py",
        BASE_CODES_DIR / "src/select_clone/top_clones.py",
        BASE_CODES_DIR / "src/alignment/alignment_intraclonal.py",
        BASE_CODES_DIR / "src/tree/clonal_tree.py",
    ]
    missing = [str(p.relative_to(ROOT_DIR)) for p in required_paths if not p.exists()]
    if missing:
        msg = (
            "ClonalTree base-codes submodule is missing/uninitialized. "
            "Run: git submodule update --init --recursive"
        )
        logs.append(
            {
                "step": "submodule_check",
                "cmd": "git submodule status services/clonaltree/base-codes",
                "ok": False,
                "out": f"{msg}\nMissing: {', '.join(missing)}",
            }
        )
        return False, msg

    logs.append(
        {
            "step": "submodule_check",
            "cmd": "verify services/clonaltree/base-codes",
            "ok": True,
            "out": "Submodule files present.",
        }
    )
    return True, ""


def detect_clonotype_ref() -> Dict[str, Optional[str]]:
    tag = (os.environ.get("CLONOTYPE_PINNED_TAG") or "").strip() or None
    commit = (os.environ.get("CLONOTYPE_PINNED_SHA") or "").strip() or None

    if BASE_CODES_DIR.exists():
        if commit is None:
            try:
                commit = (
                    subprocess.check_output(
                        ["git", "-C", str(BASE_CODES_DIR), "rev-parse", "HEAD"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    .strip()
                    or None
                )
            except Exception:
                commit = None
        if tag is None:
            try:
                detected = (
                    subprocess.check_output(
                        ["git", "-C", str(BASE_CODES_DIR), "describe", "--tags", "--exact-match"],
                        stderr=subprocess.DEVNULL,
                        text=True,
                    )
                    .strip()
                    or None
                )
                tag = detected
            except Exception:
                tag = None

    ref = tag or commit
    return {
        "tag": tag,
        "commit": commit,
        "ref": ref,
    }


def parse_repertoire_two_levels(
    path: Path,
    preview_limit: int = 500,
) -> Tuple[List[Dict[str, Any]], Dict[str, List[Any]], Dict[str, Any], Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    clones_all: Dict[str, List[Any]] = {"clone_id": [], "abundance": [], "seqs": []}
    stats: Dict[str, Any] = {"n_clones": 0, "total_seqs": 0}

    table_payload: Dict[str, Any] = {
        "filename": path.name,
        "format": "tsv",
        "columns": REPERTOIRE_TABLE_COLUMNS,
        "rows": [],
        "total_rows": 0,
        "truncated": False,
    }

    if not path.exists():
        return records, clones_all, stats, table_payload

    lines = path.read_text(errors="ignore").splitlines()
    for line in lines:
        if not line.strip():
            continue
        parts = line.rstrip("\n").split("\t")
        if len(parts) < 3:
            continue
        if len(parts) < 7:
            parts += [""] * (7 - len(parts))
        if len(parts) > 7:
            parts = parts[:6] + ["\t".join(parts[6:])]

        clone_label = parts[0].strip()
        clone_id_match = re.search(r"(\d+)\s*$", clone_label)
        clone_id = clone_id_match.group(1) if clone_id_match else clone_label

        try:
            abundance = float(parts[1])
        except Exception:
            abundance = 0.0

        try:
            seq_count = int(float(parts[2]))
        except Exception:
            seq_count = 0

        record = {
            "clone_label": clone_label,
            "clone_id": clone_id,
            "abundance": abundance,
            "sequence_count": seq_count,
            "clonotype_profile": parts[3].strip(),
            "v_call": parts[4].strip(),
            "j_call": parts[5].strip(),
            "clonotype_members": parts[6].strip(),
        }
        records.append(record)

        clones_all["clone_id"].append(clone_id)
        clones_all["abundance"].append(abundance)
        clones_all["seqs"].append(seq_count)
        stats["total_seqs"] += seq_count

    stats["n_clones"] = len(records)

    preview = records[:preview_limit]
    table_payload["rows"] = preview
    table_payload["total_rows"] = len(records)
    table_payload["truncated"] = len(records) > preview_limit

    return records, clones_all, stats, table_payload


def parse_tree_name(name: str, run_name: str) -> Tuple[Optional[int], Optional[str]]:
    m = re.match(rf"^{re.escape(run_name)}_(\d+)_(.+)\.nk$", name)
    if not m:
        return None, None
    try:
        clone_rank = int(m.group(1))
    except Exception:
        clone_rank = None
    limit_label = m.group(2)
    return clone_rank, limit_label


def collect_tree_paths(out_dir: Path, run_name: str, limit_order: List[str]) -> List[Path]:
    paths = list(out_dir.glob(f"{run_name}_*.nk"))
    limit_pos = {value: idx for idx, value in enumerate(limit_order)}

    def _key(pth: Path):
        clone_rank, limit_label = parse_tree_name(pth.name, run_name)
        rank_key = clone_rank if clone_rank is not None else 10**9
        limit_key = limit_pos.get(limit_label or "", len(limit_pos))
        return (rank_key, limit_key, str(limit_label or ""), pth.name)

    return sorted(paths, key=_key)


def zip_artifacts(src_dir: Path, name: str) -> Tuple[Optional[Path], Optional[str]]:
    """Build the bundle zip on disk and return (path, name) — no base64."""
    if not src_dir.exists():
        return None, None
    zip_path = src_dir.parent / f"{name}_clonaltree_outputs.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in src_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=path.relative_to(src_dir))
        return zip_path, zip_path.name
    except Exception:
        return None, None


async def decode_request(request: Request, tmp: Path) -> Tuple[Path, Dict[str, Any]]:
    ct = (request.headers.get("content-type") or "").lower()
    params: Dict[str, Any] = {}

    if "application/json" in ct:
        body = await request.json()
        if not isinstance(body, dict):
            raise ValueError("JSON body must be an object")
        params = body.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        file_path = body.get("file_path")
        if not file_path:
            raise ValueError("file_path is required in JSON mode")
        src = Path(file_path)
        if not src.exists():
            raise ValueError(f"file_path does not exist: {file_path}")
        dst = tmp / (src.name or "upload.tsv")
        shutil.copy2(src, dst)
        return dst, params

    form = await request.form()
    raw_params = form.get("params") or "{}"
    if isinstance(raw_params, bytes):
        raw_params = raw_params.decode("utf-8", "ignore")
    try:
        params = json.loads(raw_params) if raw_params else {}
    except Exception:
        params = {}

    upload = form.get("file")
    if upload is None or not isinstance(upload, UploadFile):
        raise ValueError("file is required (tsv)")
    raw = await upload.read()
    dst = tmp / (upload.filename or "upload.tsv")
    dst.write_bytes(raw)
    return dst, params


def cleanup_alignment_sidecars(out_dir: Path, run_name: str, clone_idx: str, limit_label: str):
    stems = [
        f"{run_name}_{clone_idx}_{limit_label}_all.aln.fa",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq.fasta",
        f"{run_name}_{clone_idx}_{limit_label}.aln",
        f"{run_name}_{clone_idx}_{limit_label}_uniq.aln.fa",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq_uniq.aln.fa",
        f"{run_name}_{clone_idx}_{limit_label}_aligned_regions.txt",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq.aln",
    ]
    for stem in stems:
        try:
            (out_dir / stem).unlink(missing_ok=True)  # type: ignore[attr-defined]
        except Exception:
            try:
                (out_dir / stem).unlink()
            except Exception:
                pass


def parse_fasta_headers(path: Path) -> List[Tuple[str, float]]:
    """Parse FASTA headers in the form '>sequence_id@count' into (label, count)."""
    headers: List[Tuple[str, float]] = []
    if not path.exists():
        return headers
    try:
        lines = path.read_text(errors="ignore").splitlines()
    except Exception:
        return headers

    for line in lines:
        if not line.startswith(">"):
            continue
        header = line[1:].strip()
        if not header:
            continue
        token = header.split()[0]
        if "@" in token:
            seq_id, raw_count = token.split("@", 1)
            seq_id = seq_id.strip()
            try:
                count = float(raw_count)
            except Exception:
                count = 1.0
        else:
            seq_id = token.strip()
            count = 1.0
        if not seq_id:
            continue
        headers.append((seq_id, max(1.0, count)))
    return headers


def parse_seq_info_lookup(path: Path) -> Dict[str, Dict[str, Any]]:
    """Load seq_info TSV into a sequence_id -> row mapping."""
    lookup: Dict[str, Dict[str, Any]] = {}
    if not path.exists():
        return lookup

    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as handle:
            reader = csv.DictReader(handle, delimiter="\t")
            if not reader.fieldnames:
                return lookup
            for raw_row in reader:
                if not isinstance(raw_row, dict):
                    continue
                seq_id = str(raw_row.get("sequence_id") or "").strip()
                if not seq_id:
                    continue
                row: Dict[str, Any] = {}
                for key, value in raw_row.items():
                    if key is None:
                        continue
                    normalized_key = str(key).strip()
                    if not normalized_key:
                        continue
                    row[normalized_key] = "" if value is None else str(value).strip()
                row["sequence_id"] = seq_id
                lookup[seq_id] = row
    except Exception:
        return {}

    return lookup


def build_tree_annotations(seq_source: Path, seq_info_path: Path) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
    """
    Build per-tree annotation rows keyed by tree label.
    Labels are taken from selected FASTA headers so they match Newick tip labels.
    """
    headers = parse_fasta_headers(seq_source)
    seq_info_lookup = parse_seq_info_lookup(seq_info_path)

    annotations: List[Dict[str, Any]] = []
    label_to_sequence_id: Dict[str, str] = {}
    seen_labels: set[str] = set()

    for label, duplicate_count in headers:
        if not label or label in seen_labels:
            continue
        seen_labels.add(label)

        row: Dict[str, Any] = {
            "label": label,
            "duplicate_count": duplicate_count,
        }

        seq_info_row = seq_info_lookup.get(label)
        if seq_info_row:
            for key, value in seq_info_row.items():
                if key == "label":
                    continue
                row[key] = value

        sequence_id = str(row.get("sequence_id") or "").strip()
        if not sequence_id and label != "germline":
            sequence_id = label
            row["sequence_id"] = sequence_id

        if sequence_id:
            label_to_sequence_id[label] = sequence_id

        annotations.append(row)

    return annotations, label_to_sequence_id


def parse_fasta_abundance(path: Path) -> Dict[str, float]:
    """Parse selected FASTA headers into abundance mapping keyed by tree label."""
    out: Dict[str, float] = {}
    for label, count in parse_fasta_headers(path):
        out[label] = max(1.0, out.get(label, 0.0) + max(1.0, count))
    return out


def copy_if_exists(src: Path, dst: Path) -> None:
    try:
        if src.exists():
            shutil.copy2(src, dst)
    except Exception:
        pass


# ---------- handlers ----------
@app.get(ROUTES["spec"])
def spec_handler():
    try:
        param_schema = _read_json(
            PARAM_SCHEMA_PATH,
            {"type": "object", "properties": {}, "required": []},
        )
        ui_hints = {**DEFAULT_UI, **(UI_JSON or {})}
        return ok(
            {
                "id": METHOD_ID,
                "name": SPEC_JSON.get("name") or "ClonalTree (bridge)",
                "version": SPEC_JSON.get("version") or "0.1.0",
                "accepts": SPEC_JSON.get("accepts") or DEFAULT_ACCEPTS,
                "paramSchema": param_schema,
                "uiHints": ui_hints,
            }
        )
    except Exception as e:
        return err(f"spec error: {e}", 500)


if not STRICT_CONTRACT_ROUTES:

    @app.get("/spec")  # type: ignore
    def _spec_alias():
        return spec_handler()


@app.post(ROUTES["run"])
async def run_handler(request: Request):
    tmp = Path(tempfile.mkdtemp(prefix="clonaltree_"))
    logs: List[dict] = []
    warnings: List[str] = []
    try:
        try:
            input_path, params = await decode_request(request, tmp)
        except Exception as e:
            return err(str(e), logs=logs)

        submodule_ok, submodule_error = ensure_clonotype_submodule(logs)
        if not submodule_ok:
            return err(submodule_error, logs=logs)

        validation = validate_clonaltree_input(input_path, params)
        if not validation.ok:
            logs.append(
                {
                    "step": "input_validation",
                    "cmd": "validate input file and parameters",
                    "ok": False,
                    "out": validation.error or "Input validation failed.",
                }
            )
            return err(
                validation.error or "Input validation failed.",
                logs=logs,
                details=validation.error_details or None,
            )

        warnings.extend(validation.warnings)
        logs.append(
            {
                "step": "input_validation",
                "cmd": "validate input file and parameters",
                "ok": True,
                "out": (
                    f"input={input_path.name}; "
                    f"warnings={len(validation.warnings)}"
                ),
            }
        )

        # Parameters (backward-compatible defaults + upstream alignment)
        run_name = slugify(params.get("run_name") or input_path.stem or "clonaltree")
        abundance_threshold = clamp_int(params.get("abundance_threshold"), 3, 0)

        clone_thr_raw = params.get("clone_cdr3_similarity", params.get("initial_clustering_threshold", 0.7))
        clone_thr = clamp_float(clone_thr_raw, 0.7, 0.0, 1.0)

        top_clones_raw = params.get("top_clones", params.get("number_top_clone", 5))
        top_clones_req = clamp_int(top_clones_raw, 5, 1)

        clonotype_limits_raw = params.get("clonotypes_per_clone") or "30, 200"
        clonotype_limits = parse_clonotype_limits(str(clonotype_limits_raw))
        if not clonotype_limits:
            clonotype_limits = [30]
            warnings.append("No clonotype limits parsed; defaulting to 30.")

        use_refinement = parse_bool(params.get("use_refinement"), True)
        use_input_alignment = parse_bool(params.get("use_input_alignment"), False)
        use_abundance = parse_bool(params.get("tree_use_abundance"), True)
        revision = parse_bool(params.get("tree_revision"), True)

        v_distance = clamp_choice_int(params.get("v_distance"), 1, {1, 2, 3, 4})
        j_distance = clamp_choice_int(params.get("j_distance"), 2, {1, 2, 3, 4})
        cdr3_distance = clamp_choice_int(params.get("cdr3_distance"), 2, {1, 2, 3, 4})
        combine_distance = clamp_choice_int(params.get("combine_distance"), 1, {1, 2, 3})
        merge_singleton = parse_bool(params.get("merge_singleton"), True)

        clonotype_method = clamp_choice_str(params.get("clonotype_method"), "L3", {"L1", "L2", "L3", "L4", "L5"})
        clonotype_similarity_threshold = clamp_float(
            params.get("clonotype_similarity_threshold"),
            0.8,
            0.0,
            1.0,
        )

        if "number_top_clone" in params and "top_clones" not in params:
            warnings.append("Parameter 'number_top_clone' is deprecated; use 'top_clones'.")
        if "initial_clustering_threshold" in params and "clone_cdr3_similarity" not in params:
            warnings.append("Parameter 'initial_clustering_threshold' is deprecated; use 'clone_cdr3_similarity'.")

        out_dir = tmp / "output"
        out_dir.mkdir(parents=True, exist_ok=True)

        # These keys intentionally mirror upstream config/setting.py names so
        # wrapper params map directly to clonotype's expected configuration surface.
        settings = {
            "ABUNDANCE_THRESHOLD": abundance_threshold,
            "INITIAL_CLUSTERING_THRESHOLD": clone_thr,
            "V_DISTANCE": v_distance,
            "J_DISTANCE": j_distance,
            "CDR3_DISTANCE": cdr3_distance,
            "COMBINE_DISTANCE": combine_distance,
            "MERGE_SINGLETON": 1 if merge_singleton else 0,
            "CLONOTYPE_METHOD": clonotype_method,
            "SIMILARITY_THRESHOLD": clonotype_similarity_threshold,
            "NUMBER_TOP_CLONE": top_clones_req,
            "REMOVE_INTERMEDIATE_FILES": True,
            "CLONOTYPES_PER_CLONE": [str(v) for v in clonotype_limits],
            "RUN_REFINEMENT": use_refinement,
            "TREE_USE_ABUNDANCE": use_abundance,
            "TREE_REVISION": revision,
            "RUN_NAME": run_name,
        }
        settings_path = out_dir / "clonotype_settings.resolved.json"
        settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        logs.append(
            {
                "step": "config_generation",
                "cmd": "generate resolved clonotype settings",
                "ok": True,
                "out": str(settings_path.name),
            }
        )

        muscle_ok, muscle_major, muscle_raw = ensure_muscle_v5(logs)
        if not muscle_ok:
            return err("MUSCLE v5 is required; detected an incompatible version", logs=logs)

        clone_thr_str = str(clone_thr)

        format_tsv = out_dir / "format_labeling_imgt_airr.tsv"
        legacy_seq_prefix = out_dir / f"{run_name}_seq_Fo.txt"
        legacy_formatted_seq = out_dir / f"{run_name}_seq_Fo_V_CDR3_Jseq.txt"

        initial_cluster_tsv = out_dir / f"sameVJ_noallele_CDR3_{clone_thr_str}.tsv"
        initial_clusters_fo_tsv = out_dir / "initial_clusters_Fo.tsv"
        legacy_initial_cluster_raw = out_dir / f"{run_name}_sameVJ_noallele_CDR3_{clone_thr_str}.txt"
        legacy_initial_cluster_fmt = out_dir / f"{run_name}_initial_clusters_Fo.txt"

        clone_v_cdr3_j_tsv = out_dir / "clone_V_CDR3_J.tsv"
        final_clusters_fo_tsv = out_dir / "final_clusters_Fo.tsv"
        legacy_refined_raw = out_dir / f"{run_name}_seq_Fo_V_CDR3_Jseq_clone_V_CDR3_J.txt"
        legacy_final_cluster_fmt = out_dir / f"{run_name}_final_clusters_Fo.txt"

        repertoire_info_tsv = out_dir / "repertoire_two_levels_info.tsv"
        final_seq_info_tsv = out_dir / "final_clusters_seq_info.tsv"
        legacy_repertoire_info = out_dir / f"{run_name}_repertoire_two_levels_info.txt"
        legacy_final_seq_info = out_dir / f"{run_name}_final_clusters_seq_info.txt"

        # Step 1: format AIRR input
        ok1 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "src/format/format_labeling_imgt_airr.py"),
                "-a",
                str(input_path),
                "-o",
                str(out_dir),
                "-t",
                str(abundance_threshold),
            ],
            cwd=BASE_CODES_DIR,
            step="format_input",
            logs=logs,
        )
        if not ok1 or not format_tsv.exists():
            return err("formatting failed", logs=logs)
        copy_if_exists(format_tsv, legacy_formatted_seq)
        copy_if_exists(format_tsv, legacy_seq_prefix)

        # Step 2: initial clustering
        ok2 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "src/cluster/initial_clustering.py"),
                "-i",
                str(format_tsv),
                "-o",
                str(out_dir),
                "-t",
                clone_thr_str,
            ],
            cwd=BASE_CODES_DIR,
            step="initial_clustering",
            logs=logs,
        )
        if not ok2 or not initial_cluster_tsv.exists() or not initial_clusters_fo_tsv.exists():
            return err("initial clustering failed", logs=logs)
        copy_if_exists(initial_cluster_tsv, legacy_initial_cluster_raw)
        copy_if_exists(initial_clusters_fo_tsv, legacy_initial_cluster_fmt)

        # Step 3: refinement (optional)
        if use_refinement:
            ok3 = run_capture(
                [
                    sys.executable,
                    str(BASE_CODES_DIR / "src/refinement/refinement.py"),
                    "-f",
                    str(initial_cluster_tsv),
                    "-l",
                    str(initial_clusters_fo_tsv),
                    "-v",
                    str(v_distance),
                    "-j",
                    str(j_distance),
                    "-c",
                    str(cdr3_distance),
                    "-d",
                    str(combine_distance),
                    "-m",
                    "1" if merge_singleton else "0",
                    "-o",
                    str(out_dir),
                ],
                cwd=BASE_CODES_DIR,
                step="refinement",
                logs=logs,
            )
            if not ok3 or not clone_v_cdr3_j_tsv.exists() or not final_clusters_fo_tsv.exists():
                return err("refinement failed", logs=logs)
        else:
            try:
                shutil.copy2(initial_cluster_tsv, clone_v_cdr3_j_tsv)
                shutil.copy2(initial_clusters_fo_tsv, final_clusters_fo_tsv)
                logs.append(
                    {
                        "step": "refinement_skip",
                        "cmd": "skip refinement (copy initial clusters)",
                        "ok": True,
                        "out": str(clone_v_cdr3_j_tsv.name),
                    }
                )
            except Exception as e:
                return err(f"failed to prepare non-refined clusters: {e}", logs=logs)

        copy_if_exists(clone_v_cdr3_j_tsv, legacy_refined_raw)
        copy_if_exists(final_clusters_fo_tsv, legacy_final_cluster_fmt)

        # Step 4: two-level hierarchy + seq info
        ok4 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "src/cluster/two_level_clonal_info.py"),
                "-f",
                str(clone_v_cdr3_j_tsv),
                "-c",
                str(final_clusters_fo_tsv),
                "-n",
                run_name,
                "-m",
                clonotype_method,
                "-t",
                str(clonotype_similarity_threshold),
                "-o",
                str(out_dir),
            ],
            cwd=BASE_CODES_DIR,
            step="two_level_clonal_info",
            logs=logs,
        )
        if not ok4 or not repertoire_info_tsv.exists() or not final_seq_info_tsv.exists():
            return err("two-level clone/clonotype step failed", logs=logs)

        copy_if_exists(repertoire_info_tsv, legacy_repertoire_info)
        copy_if_exists(final_seq_info_tsv, legacy_final_seq_info)

        repertoire_rows, repertoire_all_clones, stats_counts, repertoire_table = parse_repertoire_two_levels(
            repertoire_info_tsv
        )

        selected_clones = min(top_clones_req, stats_counts.get("n_clones", 0) or 0)
        if selected_clones <= 0:
            warnings.append("No clones found; skipping alignment and tree construction.")

        # Step 5: select top clones for per-clone alignment
        if selected_clones > 0:
            ok5 = run_capture(
                [
                    sys.executable,
                    str(BASE_CODES_DIR / "src/select_clone/top_clones.py"),
                    "-r",
                    str(repertoire_info_tsv),
                    "-c",
                    str(final_seq_info_tsv),
                    "-o",
                    str(out_dir),
                    "-s",
                    str(selected_clones),
                ],
                cwd=BASE_CODES_DIR,
                step="select_clones",
                logs=logs,
            )
            if not ok5:
                return err("failed to prepare per-clone inputs", logs=logs)

            for idx in range(1, selected_clones + 1):
                copy_if_exists(out_dir / f"{idx}_seq_info.tsv", out_dir / f"{run_name}_{idx}_seq_info.txt")

        # Step 6: alignment + tree per clone/limit
        node_abundances_by_tree: Dict[str, Dict[str, float]] = {}
        annotations_by_tree: Dict[str, List[Dict[str, Any]]] = {}
        label_to_sequence_id_by_tree: Dict[str, Dict[str, str]] = {}
        for idx in range(1, selected_clones + 1):
            clone_seq_info = out_dir / f"{idx}_seq_info.tsv"
            if not clone_seq_info.exists():
                warnings.append(f"Missing seq info for clone rank {idx}; skipping.")
                continue

            for limit in clonotype_limits:
                limit_label = str(limit)
                align_ok = run_capture(
                    [
                        sys.executable,
                        str(BASE_CODES_DIR / "src/alignment/alignment_intraclonal.py"),
                        "-a",
                        str(input_path),
                        "-f",
                        str(clone_seq_info),
                        "-n",
                        str(out_dir / f"{run_name}_{idx}"),
                        "-s",
                        limit_label,
                    ]
                    + (["--use-input-alignment"] if use_input_alignment else []),
                    cwd=BASE_CODES_DIR,
                    step=f"alignment_clone{idx}_limit{limit_label}",
                    logs=logs,
                )
                if not align_ok:
                    warnings.append(f"Alignment failed for clone rank {idx} ({limit_label}).")
                    continue

                aln_fa = out_dir / f"{run_name}_{idx}_{limit_label}_uniq.aln.fa"
                legacy_aln_fa = out_dir / f"{run_name}_{idx}_{limit_label}_selected_seq_uniq.aln.fa"
                copy_if_exists(aln_fa, legacy_aln_fa)

                if not aln_fa.exists():
                    warnings.append(f"No aligned fasta for clone rank {idx} ({limit_label}); skipping tree.")
                    continue

                tree_out = out_dir / f"{run_name}_{idx}_{limit_label}.nk"
                tree_ok = run_capture(
                    [
                        sys.executable,
                        str(BASE_CODES_DIR / "src/tree/clonal_tree.py"),
                        "-i",
                        str(aln_fa),
                        "-o",
                        str(tree_out),
                        "-a",
                        "0" if use_abundance else "1",
                        "-r",
                        "0" if revision else "1",
                    ],
                    cwd=BASE_CODES_DIR,
                    step=f"tree_clone{idx}_limit{limit_label}",
                    logs=logs,
                )
                if not tree_ok:
                    warnings.append(f"Tree construction failed for clone rank {idx} ({limit_label}).")
                else:
                    seq_source = out_dir / f"{run_name}_{idx}_{limit_label}_selected_seq.fasta"
                    abund_map = parse_fasta_abundance(seq_source)
                    if abund_map:
                        node_abundances_by_tree[tree_out.name] = abund_map
                    ann_rows, label_map = build_tree_annotations(seq_source, clone_seq_info)
                    annotations_by_tree[tree_out.name] = ann_rows
                    if label_map:
                        label_to_sequence_id_by_tree[tree_out.name] = label_map

                cleanup_alignment_sidecars(out_dir, run_name, str(idx), limit_label)

        tree_paths = collect_tree_paths(out_dir, run_name, [str(v) for v in clonotype_limits])
        logs.append(
            {
                "step": "tree_ordering",
                "cmd": "sort trees by clone rank, then by user-specified clonotype limit order",
                "ok": True,
                "out": ", ".join([p.name for p in tree_paths]) if tree_paths else "no trees",
            }
        )

        top_clone_records = repertoire_rows[:selected_clones]

        trees: List[str] = []
        node_abundances: List[Dict[str, float]] = []
        annotations: List[List[Dict[str, Any]]] = []
        label_to_sequence_id: List[Dict[str, str]] = []
        clones_aligned: Dict[str, List[Any]] = {"clone_id": [], "abundance": [], "seqs": []}

        for p in tree_paths:
            try:
                trees.append(p.read_text().strip())
            except Exception:
                continue

            node_abundances.append(node_abundances_by_tree.get(p.name, {}))
            annotations.append(annotations_by_tree.get(p.name, []))
            label_to_sequence_id.append(label_to_sequence_id_by_tree.get(p.name, {}))

            clone_rank, _ = parse_tree_name(p.name, run_name)
            if clone_rank is not None and 1 <= clone_rank <= len(top_clone_records):
                rec = top_clone_records[clone_rank - 1]
                clones_aligned["clone_id"].append(str(rec.get("clone_id", "")))
                clones_aligned["abundance"].append(float(rec.get("abundance", 0.0)))
                clones_aligned["seqs"].append(int(rec.get("sequence_count", 0)))
            else:
                clones_aligned["clone_id"].append(str(clone_rank or ""))
                clones_aligned["abundance"].append(0.0)
                clones_aligned["seqs"].append(0)

        provenance_ref = detect_clonotype_ref()
        provenance = {
            "clonotype_submodule": provenance_ref,
            "muscle": {
                "major": muscle_major,
                "version_raw": muscle_raw,
            },
            "container": {
                "image_ref": (os.environ.get("CLONALTREE_IMAGE_REF") or "").strip() or None,
                "image_digest": (os.environ.get("CLONALTREE_IMAGE_DIGEST") or "").strip() or None,
            },
        }

        stats = {
            "method": METHOD_ID,
            "clone_threshold": clone_thr,
            "abundance_threshold": abundance_threshold,
            "top_clones": top_clones_req,
            "clonotype_limits": [str(v) for v in clonotype_limits],
            "use_refinement": use_refinement,
            "use_abundance": use_abundance,
            "revision": revision,
            "n_clones": stats_counts.get("n_clones", 0),
            "n_trees": len(trees),
            "total_seqs": stats_counts.get("total_seqs", 0),
            "input_basename": input_path.name,
            "clonotype_method": clonotype_method,
            "clonotype_similarity_threshold": clonotype_similarity_threshold,
            "use_input_alignment": use_input_alignment,
        }

        logs.append(
            {
                "step": "post_processing",
                "cmd": "build response payload and clone/tree alignment",
                "ok": True,
                "out": f"trees={len(trees)} clones_aligned={len(clones_aligned['clone_id'])}",
            }
        )
        logs.append(
            {
                "step": "output_collection",
                "cmd": "collect trees, abundances, and tables",
                "ok": True,
                "out": f"repertoire_rows={repertoire_table.get('total_rows', 0)}",
            }
        )

        logs_path = out_dir / "pipeline_logs.json"
        provenance_path = out_dir / "provenance.json"
        try:
            logs_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
            provenance_path.write_text(json.dumps(provenance, indent=2), encoding="utf-8")
        except Exception:
            pass

        bundle_path, bundle_filename = zip_artifacts(out_dir, run_name)
        logs.append(
            {
                "step": "artifact_packaging",
                "cmd": "zip output directory",
                "ok": bundle_path is not None,
                "out": bundle_filename or "artifact packaging failed",
            }
        )

        try:
            logs_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
            bundle_path, bundle_filename = zip_artifacts(out_dir, run_name)
        except Exception:
            pass

        # Build artifact_files referencing on-disk paths — no base64 anywhere.
        artifact_files: List[Dict[str, Any]] = []
        if bundle_path is not None and bundle_path.exists():
            artifact_files.append({
                "path": str(bundle_path),
                "filename": bundle_filename or "clonaltree_outputs.zip",
                "kind": "zip",
                "role": "clone_bundle_zip",
                "content_type": "application/zip",
                "previewable": False,
            })

        return ok(
            {
                "ok": True,
                "trees": trees,
                "annotations": annotations,
                "figures": None,
                "node_abundances": node_abundances,
                "label_to_sequence_id": label_to_sequence_id,
                "clones": clones_aligned,
                "clone_catalog": repertoire_all_clones,
                "tables": {
                    "repertoire_two_levels_info": repertoire_table,
                },
                "provenance": provenance,
                "stats": stats,
                "warnings": warnings,
                "logs": logs,
                "artifact_files": artifact_files,
                "artifact_name": bundle_filename,
            }
        )

    except Exception as e:
        return err(f"run error: {e}", status_code=500, logs=logs)
    # NOTE: do NOT rmtree(tmp) here — the artifact_files paths point into tmp
    # and materialize_artifacts (running after this handler returns) needs to
    # copy them. The OS cleans up /tmp when the job_runner process exits.


if not STRICT_CONTRACT_ROUTES:

    @app.post("/run")  # type: ignore
    async def _run_alias(request: Request):
        return await run_handler(request)


# ---------- Async job execution (/jobs contract) ----------
from job_manager import JobManager  # noqa: E402

job_manager = JobManager(METHOD_ID)


def run_job_sync(file_path, params) -> Tuple[int, Any]:
    """Invoke the existing /run handler synchronously in this (child) process."""
    import asyncio

    async def _call():
        body = json.dumps({"file_path": file_path, "params": params or {}}).encode("utf-8")
        scope = {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": ROUTES["run"],
            "raw_path": ROUTES["run"].encode("utf-8"),
            "query_string": b"",
            "root_path": "",
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("ascii")),
            ],
            "client": ("127.0.0.1", 0),
            "server": ("127.0.0.1", 80),
        }
        sent = False

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        return await run_handler(Request(scope, receive))

    resp = asyncio.run(_call())
    raw = resp.body
    if isinstance(raw, (bytes, bytearray)):
        payload = json.loads(raw.decode("utf-8"))
    else:
        payload = json.loads(raw)
    return resp.status_code, payload


@app.post(ROUTES["jobs"])
async def submit_job_endpoint(request: Request):
    try:
        body = await request.json()
    except Exception:
        return err("JSON body required", 400)
    if not isinstance(body, dict):
        return err("JSON body must be an object", 400)
    file_path = body.get("file_path")
    params = body.get("params") or {}
    run_id = body.get("run_id")
    try:
        job_id = job_manager.submit(file_path=file_path, params=params, run_id=run_id)
    except Exception as e:  # noqa: BLE001
        return err(f"Failed to start job: {e}", 500)
    return ok({"ok": True, "job_id": job_id, "status": "QUEUED"})


@app.get(ROUTES["jobStatus"])
async def job_status_endpoint(job_id: str):
    st = job_manager.status(job_id)
    if st is None:
        return err("Job not found", 404)
    return ok(st)


@app.get(ROUTES["jobResult"])
async def job_result_endpoint(job_id: str):
    payload, code = job_manager.result(job_id)
    if code == 404:
        return err("Job not found", 404)
    if code == 409:
        return err("Job not finished", 409)
    return ok(payload)


@app.post(ROUTES["jobCancel"])
async def job_cancel_post_endpoint(job_id: str):
    st = job_manager.cancel(job_id)
    if st is None:
        return err("Job not found", 404)
    return ok(st)


@app.delete(ROUTES["jobCancel"])
async def job_cancel_delete_endpoint(job_id: str):
    st = job_manager.cancel(job_id)
    if st is None:
        return err("Job not found", 404)
    return ok(st)
