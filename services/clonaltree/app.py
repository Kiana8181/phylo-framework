# services/clonaltree/app.py
from __future__ import annotations

import base64
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
from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

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
ROUTES = _read_json(ROUTES_JSON_PATH, {"spec": "/spec", "run": "/run"})
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


def err(msg, status_code: int = 400, logs: Optional[List[dict]] = None) -> JSONResponse:
    payload: Dict[str, Any] = {"ok": False, "error": msg}
    if logs:
        payload["logs"] = logs
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


def parse_clonotype_limits(raw: str) -> List[str | int]:
    if not raw:
        return []
    vals: List[str | int] = []
    for tok in re.split(r"[,\s]+", raw.strip()):
        if not tok:
            continue
        if tok.lower() == "all":
            vals.append("all")
            continue
        try:
            v = int(tok)
            if v > 0:
                vals.append(v)
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

    m = re.search(r"[Vv]ersion\s*([0-9]+)", out)
    if not m:
        m = re.search(r"[Vv]([0-9]+)\.", out)
    if m:
        try:
            return int(m.group(1)), out
        except Exception:
            pass
    return None, out


def ensure_muscle_v3(logs: List[dict]) -> bool:
    major, raw = muscle_major_version()
    ok_flag = major is not None and major < 5
    logs.append(
        {
            "step": "muscle_version",
            "cmd": "muscle -version",
            "ok": ok_flag,
            "out": raw,
        }
    )
    return ok_flag


def parse_clone_summary(path: Path) -> Tuple[Dict[str, List[Any]], Dict[str, Any]]:
    clones: Dict[str, List[Any]] = {"clone_id": [], "abundance": [], "seqs": []}
    stats: Dict[str, Any] = {"n_clones": 0, "total_seqs": 0}
    if not path.exists():
        return clones, stats

    lines = path.read_text(errors="ignore").splitlines()
    for line in lines:
        parts = line.strip().split("\t")
        if len(parts) < 3:
            continue
        clone_label = parts[0].split()[-1] if parts[0] else str(len(clones["clone_id"]))
        clones["clone_id"].append(clone_label)
        try:
            clones["abundance"].append(float(parts[1]))
        except Exception:
            clones["abundance"].append(None)
        try:
            seqs = int(float(parts[2]))
        except Exception:
            seqs = None
        clones["seqs"].append(seqs)
        if seqs:
            stats["total_seqs"] += seqs

    stats["n_clones"] = len(clones["clone_id"])
    return clones, stats


def collect_tree_paths(out_dir: Path, run_name: str) -> List[Path]:
    paths = []
    for p in out_dir.glob(f"{run_name}_*.nk"):
        paths.append(p)

    def _key(pth: Path):
        m = re.search(r"_([0-9]+)_([A-Za-z0-9]+)\.nk$", pth.name)
        if m:
            try:
                return (int(m.group(1)), m.group(2))
            except Exception:
                return (m.group(1), m.group(2))
        return (pth.name,)

    return sorted(paths, key=_key)


def zip_artifacts(src_dir: Path, name: str) -> Tuple[Optional[str], Optional[str]]:
    if not src_dir.exists():
        return None, None
    zip_path = src_dir.parent / f"{name}_clonaltree_outputs.zip"
    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for path in src_dir.rglob("*"):
                if path.is_file():
                    zf.write(path, arcname=path.relative_to(src_dir))
        b64 = base64.b64encode(zip_path.read_bytes()).decode("ascii")
        return b64, zip_path.name
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


def cleanup_alignment_sidecars(out_dir: Path, run_name: str, clone_idx: str, limit_label: str):
    stems = [
        f"{run_name}_{clone_idx}_{limit_label}_all.aln.fa",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq.fasta",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq.aln",
        f"{run_name}_{clone_idx}_{limit_label}_selected_seq_uniq.aln.fa",
    ]
    for stem in stems:
        try:
            (out_dir / stem).unlink(missing_ok=True)  # type: ignore[attr-defined]
        except Exception:
            try:
                (out_dir / stem).unlink()
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

        # Parameters (with sane defaults)
        run_name = slugify(params.get("run_name") or input_path.stem or "clonaltree")
        abundance_threshold = clamp_int(params.get("abundance_threshold"), 3, 1)
        clone_thr = clamp_float(params.get("clone_cdr3_similarity"), 0.7, 0.0, 1.0)
        top_clones_req = clamp_int(params.get("top_clones"), 5, 1)
        clonotype_limits_raw = params.get("clonotypes_per_clone") or "30, 200"
        clonotype_limits = parse_clonotype_limits(clonotype_limits_raw)
        if not clonotype_limits:
            clonotype_limits = [30]
            warnings.append("No clonotype limits parsed; defaulting to 30.")
        use_refinement = bool(params.get("use_refinement") if "use_refinement" in params else True)
        use_abundance = bool(params.get("tree_use_abundance") if "tree_use_abundance" in params else True)
        revision = bool(params.get("tree_revision") if "tree_revision" in params else True)

        if not ensure_muscle_v3(logs):
            return err("MUSCLE v3 is required; detected an incompatible version", logs=logs)

        out_dir = tmp / "output"
        out_dir.mkdir(parents=True, exist_ok=True)
        sorted_clusters_path = out_dir / "Sorted_clusters.p"
        common_env = {"SORTED_CLUSTERS_PATH": str(sorted_clusters_path)}

        clone_thr_str = str(clone_thr)
        seq_prefix = out_dir / f"{run_name}_seq_Fo.txt"
        formatted_seq = out_dir / f"{run_name}_seq_Fo_V_CDR3_Jseq.txt"
        cluster_prefix = out_dir / run_name
        initial_cluster_raw = out_dir / f"{run_name}_sameVJ_noallele_CDR3_{clone_thr_str}.txt"
        initial_cluster_fmt = out_dir / f"{run_name}_initial_clusters_Fo.txt"
        refined_raw = out_dir / f"{run_name}_seq_Fo_V_CDR3_Jseq_clone_V_CDR3_J.txt"
        final_cluster_fmt = out_dir / f"{run_name}_final_clusters_Fo.txt"
        repertoire_info = out_dir / f"{run_name}_repertoire_two_levels_info.txt"
        final_seq_info = out_dir / f"{run_name}_final_clusters_seq_info.txt"

        # Step 1: format AIRR input
        ok1 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "code/formatting/format_labeling_imgt_airr.py"),
                "-a",
                str(input_path),
                "-o",
                str(seq_prefix),
                "-t",
                str(abundance_threshold),
            ],
            cwd=BASE_CODES_DIR,
            step="format_input",
            logs=logs,
            extra_env=common_env,
        )
        if not ok1 or not formatted_seq.exists():
            return err("formatting failed", logs=logs)

        # Step 2: initial clustering
        ok2 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "code/clustering/initial_clustering_f.py"),
                "-i",
                str(formatted_seq),
                "-o",
                str(cluster_prefix),
                "-s",
                clone_thr_str,
            ],
            cwd=BASE_CODES_DIR,
            step="initial_clustering",
            logs=logs,
            extra_env=common_env,
        )
        if not ok2 or not initial_cluster_raw.exists():
            return err("initial clustering failed", logs=logs)

        # Step 3: format initial clusters
        ok3 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "code/formatting/format_clustering_output.py"),
                "-i",
                str(initial_cluster_raw),
                "-o",
                str(initial_cluster_fmt),
            ],
            cwd=BASE_CODES_DIR,
            step="format_initial_clusters",
            logs=logs,
            extra_env=common_env,
        )
        if not ok3 or not initial_cluster_fmt.exists():
            return err("formatting initial clusters failed", logs=logs)

        # Step 4: refinement (optional)
        if use_refinement:
            ok4 = run_capture(
                [
                    sys.executable,
                    str(BASE_CODES_DIR / "code/refinement/refinement.py"),
                    "-f",
                    str(formatted_seq),
                    "-c",
                    str(initial_cluster_fmt),
                ],
                cwd=BASE_CODES_DIR,
                step="refinement",
                logs=logs,
                extra_env=common_env,
            )
            if not ok4 or not refined_raw.exists():
                return err("refinement failed", logs=logs)
        else:
            try:
                shutil.copy2(initial_cluster_raw, refined_raw)
                logs.append(
                    {
                        "step": "refinement_skip",
                        "cmd": "skip refinement (copy initial clusters)",
                        "ok": True,
                        "out": str(refined_raw),
                    }
                )
            except Exception as e:
                return err(f"failed to prepare refined clusters: {e}", logs=logs)

        # Step 5: format final clusters
        ok5 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "code/formatting/format_clustering_output.py"),
                "-i",
                str(refined_raw),
                "-o",
                str(final_cluster_fmt),
            ],
            cwd=BASE_CODES_DIR,
            step="format_final_clusters",
            logs=logs,
            extra_env=common_env,
        )
        if not ok5 or not final_cluster_fmt.exists():
            return err("formatting final clusters failed", logs=logs)

        # Step 6: two-level hierarchy + seq info
        ok6 = run_capture(
            [
                sys.executable,
                str(BASE_CODES_DIR / "code/clustering/two_level_clonal_info.py"),
                "-f",
                str(formatted_seq),
                "-c",
                str(final_cluster_fmt),
                "-n",
                str(out_dir / run_name),
            ],
            cwd=BASE_CODES_DIR,
            step="two_level_clonal_info",
            logs=logs,
            extra_env=common_env,
        )
        if not ok6 or not repertoire_info.exists() or not final_seq_info.exists():
            return err("two-level clone/clonotype step failed", logs=logs)

        clones, stats_counts = parse_clone_summary(repertoire_info)
        selected_clones = min(top_clones_req, stats_counts.get("n_clones", 0) or 0)
        if selected_clones <= 0:
            warnings.append("No clones found; skipping alignment and tree construction.")

        # Step 7: select clones for alignment
        if selected_clones > 0:
            ok7 = run_capture(
                [
                    sys.executable,
                    str(BASE_CODES_DIR / "code/select_clone/intraclonal_study_input_creator.py"),
                    "-r",
                    str(repertoire_info),
                    "-c",
                    str(final_seq_info),
                    "-n",
                    str(out_dir / run_name),
                    "-s",
                    str(selected_clones),
                ],
                cwd=BASE_CODES_DIR,
                step="select_clones",
                logs=logs,
                extra_env=common_env,
            )
            if not ok7:
                return err("failed to prepare per-clone inputs", logs=logs)

        # Step 8: alignment + tree per clone/limit
        for idx in range(1, selected_clones + 1):
            clone_seq_info = out_dir / f"{run_name}_{idx}_seq_info.txt"
            if not clone_seq_info.exists():
                warnings.append(f"Missing seq info for clone {idx}; skipping.")
                continue
            for limit in clonotype_limits:
                limit_label = str(limit)
                align_ok = run_capture(
                    [
                        sys.executable,
                        str(BASE_CODES_DIR / "code/alignment/alignment_intraclonal.py"),
                        "-a",
                        str(input_path),
                        "-f",
                        str(clone_seq_info),
                        "-n",
                        str(out_dir / f"{run_name}_{idx}"),
                        "-s",
                        limit_label,
                    ],
                    cwd=BASE_CODES_DIR,
                    step=f"alignment_clone{idx}_limit{limit_label}",
                    logs=logs,
                    extra_env=common_env,
                )
                if not align_ok:
                    warnings.append(f"Alignment failed for clone {idx} ({limit_label}).")
                    continue

                aln_fa = out_dir / f"{run_name}_{idx}_{limit_label}_selected_seq_uniq.aln.fa"
                if not aln_fa.exists():
                    warnings.append(f"No aligned fasta for clone {idx} ({limit_label}); skipping tree.")
                    continue

                tree_out = out_dir / f"{run_name}_{idx}_{limit_label}.nk"
                tree_ok = run_capture(
                    [
                        sys.executable,
                        str(BASE_CODES_DIR / "code/tree/clonalTree.py"),
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
                    extra_env=common_env,
                )
                if not tree_ok:
                    warnings.append(f"Tree construction failed for clone {idx} ({limit_label}).")
                cleanup_alignment_sidecars(out_dir, run_name, str(idx), limit_label)

        tree_paths = collect_tree_paths(out_dir, run_name)
        trees = []
        for p in tree_paths:
            try:
                trees.append(p.read_text().strip())
            except Exception:
                continue

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
        }

        logs_path = out_dir / "pipeline_logs.json"
        try:
            logs_path.write_text(json.dumps(logs, indent=2), encoding="utf-8")
        except Exception:
            pass

        artifact_b64, artifact_name = zip_artifacts(out_dir, run_name)

        return ok(
            {
                "ok": True,
                "trees": trees,
                "annotations": [],
                "figures": None,
                "clones": clones,
                "stats": stats,
                "warnings": warnings,
                "logs": logs,
                "artifact_zip_b64": artifact_b64,
                "artifact_name": artifact_name,
            }
        )

    except Exception as e:
        return err(f"run error: {e}", status_code=500, logs=logs)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if not STRICT_CONTRACT_ROUTES:
    @app.post("/run")  # type: ignore
    async def _run_alias(request: Request):
        return await run_handler(request)
