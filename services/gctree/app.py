# services/gctree/app.py
from __future__ import annotations

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, File, Form, Request, UploadFile  # File/Form kept for legacy alias, even if unused
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------- Constants & contracts ----------
METHOD_ID = "gctree"
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

DEFAULT_ACCEPTS = ["text/fasta", "text/x-fasta", "application/octet-stream"]
DEFAULT_UI = {"requiresFile": True, "maxFiles": 1}

# Headless & deterministic env for child procs
DEFAULT_ENV = {
    "QT_QPA_PLATFORM": "offscreen",
    "MPLBACKEND": "agg",
    "XDG_RUNTIME_DIR": "/tmp/runtime-gctree",
    "LC_ALL": "C",
    "LANG": "C",
}

# ---------- FastAPI ----------
app = FastAPI(title="GCtree microservice (bridge mode)")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def ok(data, status_code: int = 200) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=data)


def err(msg, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": msg})


# ---------- helpers ----------
def _env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(DEFAULT_ENV)
    if extra:
        env.update(extra)
    try:
        Path(env["XDG_RUNTIME_DIR"]).mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return env


def run_capture(
    cmd: List[str],
    cwd: Path,
    extra_env: Optional[Dict[str, str]] = None,
    use_shell: bool = False,
) -> Dict[str, Any]:
    """
    Run a command, capture stdout+stderr, and return:
      { "cmd": "...", "ok": bool, "out": "<combined output>" }
    Never raises: we forward raw errors to users.
    """
    env = _env(extra_env)
    if use_shell:
        p = subprocess.Popen(
            " ".join(cmd),
            cwd=str(cwd),
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    else:
        p = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
    out, _ = p.communicate()
    return {"cmd": " ".join(cmd), "ok": (p.returncode == 0), "out": out}


def run_to_file(
    cmd: List[str],
    cwd: Path,
    outfile: Path,
    logs: List[dict],
    step_name: str,
    extra_env: Optional[Dict[str, str]] = None,
    use_shell: bool = False,
) -> bool:
    """
    Run a command (capturing stdout) and write that stdout to `outfile`.
    Append step logs. Return True on success (exit code 0).
    """
    step = run_capture(cmd, cwd=cwd, extra_env=extra_env, use_shell=use_shell)
    logs.append({**step, "step": step_name})
    try:
        outfile.write_text(step["out"] or "", encoding="utf-8")
    except Exception as e:
        logs.append(
            {
                "step": f"{step_name}_write",
                "ok": False,
                "out": f"Failed to write {outfile.name}: {e}",
            }
        )
        return False
    return bool(step["ok"])


def detect_ext(filename: str, content_type: str | None) -> str:
    name = (filename or "").lower()
    ext = os.path.splitext(name)[1].lstrip(".")
    if ext:
        return ext
    if content_type and "fasta" in content_type.lower():
        return "fasta"
    if content_type and "octet-stream" in content_type.lower():
        return "bin"
    return "bin"


def read_text(p: Path) -> str:
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def collect_newicks(outdir: Path, top_n: int) -> List[str]:
    nks = sorted(outdir.glob("gctree.out.inference.*.nk"))
    out: List[str] = []
    for p in nks[:top_n]:
        try:
            out.append(read_text(p).strip())
        except Exception:
            pass
    return out


def extract_newicks_from_outtree(outtree_path: Path, limit: int = 10) -> List[str]:
    """
    Extract ';'-terminated Newick trees from PHYLIP 'outtree'.
    """
    if not outtree_path.exists():
        return []
    txt = outtree_path.read_text(errors="ignore")
    buf: List[str] = []
    cur: List[str] = []
    for ch in txt:
        cur.append(ch)
        if ch == ";":
            t = "".join(cur).strip()
            if "(" in t and ")" in t:
                # normalize whitespace
                buf.append("".join(t.split()))
            cur = []
    if cur and cur[-1] == ";":
        t = "".join(cur).strip()
        if "(" in t and ")" in t:
            buf.append("".join(t.split()))
    # dedupe, preserve order
    seen = set()
    out: List[str] = []
    for t in buf:
        if t not in seen:
            out.append(t)
            seen.add(t)
        if len(out) >= limit:
            break
    return out


def zip_artifacts(outdir: Path) -> bytes:
    """
    Collect useful outputs into a zip:
      - outfile, outtree, dnapars.log, dnapars.cfg
      - deduplicated.phylip, abundances.csv, idmap.txt
      - any gctree.out.inference.* (nk, svg, p)
      - any *.p produced
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        patterns = [
            "outfile",
            "outtree",
            "dnapars.log",
            "dnapars.cfg",
            "deduplicated.phylip",
            "abundances.csv",
            "idmap.txt",
            "gctree.out.inference.*",
            "*.p",
            "*.nk",
            "*.svg",
        ]
        added = set()
        for pat in patterns:
            for p in outdir.glob(pat):
                if p.is_file() and p.name not in added:
                    try:
                        z.write(p, arcname=p.name)
                        added.add(p.name)
                    except Exception:
                        pass
    return buf.getvalue()


def collect_figures(outdir: Path) -> Dict[str, List[str]]:
    """
    Read any *image* files produced by GCtree and group them into categories.
    Values are full data URLs ready to drop into <img src="...">.
    Supports SVG/PNG/PDF.
    """
    figs: Dict[str, List[str]] = {}
    mime_by_ext = {
        "svg": "image/svg+xml",
        "png": "image/png",
        "pdf": "application/pdf",
    }

    for p in sorted(outdir.iterdir()):
        if not p.is_file():
            continue
        ext = p.suffix.lower().lstrip(".")
        if ext not in mime_by_ext:
            continue

        try:
            b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        except Exception:
            continue

        name = p.name
        # categorize by filename pattern, independent of extension
        if "abundance_rank" in name:
            key = "abundance_rank"
        elif ".tree_stats." in name or "tree_stats" in name or "pairplot" in name:
            key = "tree_stats"
        elif ".inference." in name:
            key = "phylogeny"
        else:
            key = "other"

        mime = mime_by_ext[ext]
        figs.setdefault(key, []).append(f"data:{mime};base64,{b64}")

    return figs

def early_fail(msg: str, logs: List[dict], tmp: Path) -> JSONResponse:
    artifacts_zip = zip_artifacts(tmp)
    figures = collect_figures(tmp)
    payload = {
        "ok": False,
        "trees": [],
        "figures": figures or None,
        "annotations": [],
        "clones": {"clone_id": [], "seqs": []},
        "stats": {},
        "logs": logs,
        "artifact_zip_b64": base64.b64encode(artifacts_zip).decode("ascii"),
        "artifact_name": "gctree_run_artifacts.zip",
        "error": msg,
        "render": "phylogeny" if figures else None,
    }
    return JSONResponse(status_code=400, content=payload)


# ---------- Handlers ----------
@app.get(ROUTES["spec"])
def spec_handler():
    try:
        try:
            import gctree as _g  # noqa
            pkg_ver = getattr(_g, "__version__", "unknown")
        except Exception:
            pkg_ver = "unknown"

        # Param schema comes from contracts; fall back to a minimal one if missing
        param_schema = _read_json(
            PARAM_SCHEMA_PATH,
            {
                "type": "object",
                "properties": {
                    "root": {
                        "type": "string",
                        "title": "Root ID",
                        "default": "GL",
                    },
                    "frame": {
                        "type": "string",
                        "title": "Frame (0,1,2 => 1..3)",
                        "enum": ["0", "1", "2"],
                        "default": "0",
                    },
                    "ranking_strategy": {
                        "type": "string",
                        "title": "Ranking strategy (optional)",
                        "default": "",
                    },
                    "top_n": {
                        "type": "integer",
                        "title": "How many trees to read if produced",
                        "default": 3,
                    },
                    "pipeline": {
                        "type": "string",
                        "enum": ["phylip", "scons"],
                        "default": "phylip",
                    },
                    "infer": {
                        "type": "boolean",
                        "title": "Run 'gctree infer' (if false, stop after forest)",
                        "default": True,
                    },
                },
                "required": ["root"],
            },
        )

        ui_hints = {**DEFAULT_UI, **(UI_JSON or {})}

        return ok(
            {
                "id": METHOD_ID,
                "name": SPEC_JSON.get("name") or "GCtree (bridge)",
                "version": SPEC_JSON.get("version") or pkg_ver,
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
    tmp = Path(tempfile.mkdtemp(prefix="gctree_"))
    logs: List[Dict[str, Any]] = []
    fallback_trees: List[str] = []
    try:
        ct = (request.headers.get("content-type") or "").lower()

        # -------- decode body & load input file --------
        if "application/json" in ct:
            # Called from runs service: JSON body with { file_path, params }
            body = await request.json()
            if not isinstance(body, dict):
                return err("JSON body must be an object", 400)

            p = body.get("params") or {}
            if not isinstance(p, dict):
                p = {}

            file_path = body.get("file_path")
            if not file_path or not os.path.exists(file_path):
                return err(
                    "file_path is required and must exist on the server", 400
                )

            src = Path(file_path)
            fname = src.name or "upload.bin"

            # Copy into tmp so artifacts.zip contains the original input
            path_in = tmp / fname
            try:
                shutil.copy2(src, path_in)
            except Exception:
                # fallback copy
                path_in.write_bytes(src.read_bytes())

            ext = detect_ext(fname, None)

        else:
            # Legacy fallback: multipart/form-data with fields 'params' and 'file'
            form = await request.form()

            raw_params = form.get("params") or "{}"
            if isinstance(raw_params, bytes):
                raw_params = raw_params.decode("utf-8", "ignore")

            try:
                p = json.loads(raw_params) if raw_params else {}
            except Exception:
                p = {}

            upload = form.get("file")
            if upload is None:
                return err("file is required (.fasta or a single GCtree .p)")

            raw = await upload.read()
            fname = getattr(upload, "filename", None) or "upload.bin"
            path_in = tmp / fname
            path_in.write_bytes(raw)
            ext = detect_ext(fname, getattr(upload, "content_type", None))

        # -------- parse params --------
        root = p.get("root") or "GL"

        # internal param is 0,1,2 but GCtree expects 1..3
        frame0 = int(p.get("frame") or 0)
        if frame0 < 0 or frame0 > 2:
            frame0 = 0
        frame = str(frame0 + 1)  # "1".."3"

        ranking = (p.get("ranking_strategy") or "").strip()
        top_n = int(p.get("top_n") or 3)
        pipeline = (p.get("pipeline") or "phylip").lower()
        do_infer = bool(p.get("infer") if "infer" in p else True)

        # DNAPARS / mkconfig options
        quick = bool(p.get("quick") or False)
        jumble = p.get("jumble")
        bootstrap = p.get("bootstrap")

        # Rendering / extra outputs
        idlabel = bool(p.get("idlabel") or False)
        show_mut = bool(p.get("show_nucleotide_mutations") or False)
        summarize_forest = bool(p.get("summarize_forest") or False)
        tree_stats = bool(p.get("tree_stats") or False)
        img_type = (p.get("img_type") or "svg").strip().lower()
        outbase = (p.get("outbase") or "gctree.out").strip() or "gctree.out"

        # common paths
        dedup_phylip = tmp / "deduplicated.phylip"
        abund_csv = tmp / "abundances.csv"
        idmap_txt = tmp / "idmap.txt"
        dnapars_cfg = tmp / "dnapars.cfg"
        outfile = tmp / "outfile"
        outtree = tmp / "outtree"

        # -------- run by pipeline --------
        if pipeline == "scons":
            outdir = tmp
            scons_cmd = [
                "scons",
                "-Q",
                f"input={str(path_in)}",
                f"root_id={root}",
                f"frame={frame}",
                f"outdir={str(outdir)}",
                "inference",
            ]
            step = run_capture(scons_cmd, cwd=tmp)
            logs.append({**step, "step": "scons_inference"})
            ok_pipeline = step["ok"]
            # Even under scons, we may still extract .nk if present later.

        else:
            # -------- phylip pipeline --------
            if ext in ("fa", "fasta", "fas"):
                # 1) deduplicate → write PHYLIP to file
                ok1 = run_to_file(
                    [
                        "deduplicate",
                        str(path_in),
                        "--root",
                        root,
                        "--abundance_file",
                        str(abund_csv),
                        "--idmapfile",
                        str(idmap_txt),
                    ],
                    cwd=tmp,
                    outfile=dedup_phylip,
                    logs=logs,
                    step_name="deduplicate",
                )
                if not ok1:
                    return early_fail("deduplicate failed — see logs", logs, tmp)

                # 2) mkconfig for dnapars → write dnapars.cfg
                mkconfig_cmd: List[str] = ["mkconfig"]
                if quick:
                    mkconfig_cmd.append("--quick")
                if jumble not in (None, "", 0):
                    try:
                        mk_jumble = int(jumble)
                        if mk_jumble > 0:
                            mkconfig_cmd.extend(["--jumble", str(mk_jumble)])
                    except Exception:
                        logs.append(
                            {
                                "step": "mkconfig_jumble",
                                "ok": False,
                                "out": f"Invalid jumble value: {jumble}",
                            }
                        )
                if bootstrap not in (None, "", 0):
                    try:
                        mk_boot = int(bootstrap)
                        if mk_boot > 0:
                            mkconfig_cmd.extend(["--bootstrap", str(mk_boot)])
                    except Exception:
                        logs.append(
                            {
                                "step": "mkconfig_bootstrap",
                                "ok": False,
                                "out": f"Invalid bootstrap value: {bootstrap}",
                            }
                        )

                mkconfig_cmd.extend([str(dedup_phylip), "dnapars"])

                ok2 = run_to_file(
                    mkconfig_cmd,
                    cwd=tmp,
                    outfile=dnapars_cfg,
                    logs=logs,
                    step_name="mkconfig",
                )
                if not ok2:
                    return early_fail("mkconfig failed — see logs", logs, tmp)

                # Preflight: parse PHYLIP header "<Ntax> <Nchar>"
                try:
                    hdr = (
                        dedup_phylip.read_text(errors="ignore")
                        .splitlines()[0]
                        .split()
                    )
                    ntax, nchar = int(hdr[0]), int(hdr[1])
                    logs.append(
                        {
                            "step": "phylip_header",
                            "ok": True,
                            "out": f"Ntax={ntax} Nchar={nchar}",
                        }
                    )
                except Exception:
                    logs.append(
                        {
                            "step": "phylip_header",
                            "ok": False,
                            "out": "Could not parse header",
                        }
                    )
                    return early_fail(
                        "Could not parse PHYLIP header from deduplicated.phylip",
                        logs,
                        tmp,
                    )
                if ntax < 3:
                    return early_fail(
                        f"Too few unique sequences after deduplication (Ntax={ntax}). "
                        "Need ≥3 unique sequences with some variation.",
                        logs,
                        tmp,
                    )
                if nchar < 1:
                    return early_fail(
                        "Alignment has 0 columns after deduplication.", logs, tmp
                    )

                # 3) dnapars (with shell redirection)
                step = run_capture(
                    [
                        "bash",
                        "-lc",
                        "dnapars < dnapars.cfg > dnapars.log "
                        "|| phylip dnapars < dnapars.cfg > dnapars.log",
                    ],
                    cwd=tmp,
                )
                logs.append({**step, "step": "dnapars"})
                if not outfile.exists() or outfile.stat().st_size == 0:
                    # include start of dnapars.log
                    head: List[str] = []
                    dlog = tmp / "dnapars.log"
                    if dlog.exists():
                        try:
                            head = dlog.read_text(errors="ignore").splitlines()[:40]
                        except Exception:
                            pass
                    return early_fail(
                        "DNAPARS did not produce 'outfile'. "
                        "Common causes: Ntax<3, no variable sites, or DNAPARS execution failure. "
                        "See dnapars.log head:\n" + "\n".join(head),
                        logs,
                        tmp,
                    )

                # Always parse PHYLIP outtree as a fallback set of trees (unranked)
                fallback_trees = extract_newicks_from_outtree(
                    outtree, limit=max(1, top_n)
                )

                # 4) optionally: GCtree infer
                if do_infer:
                    infer_cmd: List[str] = [
                        "gctree",
                        "infer",
                        "outfile",
                        str(abund_csv),
                        "--root",
                        root,
                        "--frame",
                        frame,
                        "--outbase",
                        outbase,
                        "--img_type",
                        img_type,
                        "--verbose",
                    ]

                    if ranking:
                        infer_cmd.extend(["--ranking_strategy", ranking])
                    if idlabel:
                        infer_cmd.append("--idlabel")
                    if show_mut:
                        infer_cmd.append("--show_nucleotide_mutations")
                    if summarize_forest:
                        infer_cmd.append("--summarize_forest")
                    if tree_stats:
                        infer_cmd.append("--tree_stats")

                    step = run_capture(infer_cmd, cwd=tmp)
                    logs.append({**step, "step": "gctree_infer"})
                    ok_pipeline = step["ok"]

                    # Fallback if GCtree render/ETE or numeric fails: return DNAPARS outtree trees
                    if not ok_pipeline:
                        logs.append(
                            {
                                "step": "fallback_outtree",
                                "ok": bool(fallback_trees),
                                "cmd": "extract_newicks_from_outtree(outtree)",
                                "out": f"Returned {len(fallback_trees)} DNAPARS "
                                "Newick tree(s) due to GCtree infer failure.",
                            }
                        )
                        ok_pipeline = bool(fallback_trees)
                else:
                    # forest-only mode – still expose DNAPARS trees to UI for visualization
                    ok_pipeline = True

            elif ext in ("p", "pickle", "bin"):
                # user provided a forest/tree; just run infer or return as artifact
                if do_infer:
                    infer_cmd = [
                        "gctree",
                        "infer",
                        str(path_in),
                        "--root",
                        root,
                        "--frame",
                        frame,
                        "--outbase",
                        outbase,
                        "--img_type",
                        img_type,
                        "--verbose",
                    ]
                    if ranking:
                        infer_cmd.extend(["--ranking_strategy", ranking])
                    if idlabel:
                        infer_cmd.append("--idlabel")
                    if show_mut:
                        infer_cmd.append("--show_nucleotide_mutations")
                    if summarize_forest:
                        infer_cmd.append("--summarize_forest")
                    if tree_stats:
                        infer_cmd.append("--tree_stats")

                    step = run_capture(infer_cmd, cwd=tmp)
                    logs.append({**step, "step": "gctree_infer"})
                    ok_pipeline = step["ok"]
                    # If it fails, we cannot use DNAPARS fallback here (no outfile).
                else:
                    ok_pipeline = True
            else:
                return err(
                    "Unsupported file. Upload a FASTA or a single GCtree pickle (.p)."
                )

        # -------- collect artifacts, trees & figures --------
        artifacts_zip = zip_artifacts(tmp)

        # Prefer GCtree .nk output; else use DNAPARS fallback trees if available
        trees = collect_newicks(tmp, top_n)
        if not trees and fallback_trees:
            trees = fallback_trees

        stats: Dict[str, Any] = {
            "pipeline": pipeline + ("+infer" if do_infer else "+forest_only"),
            "n_trees_found": len(trees),
        }
        if fallback_trees and not collect_newicks(tmp, 1):
            stats[
                "note"
            ] = "GCtree infer failed (render/numeric). Returned DNAPARS outtree trees (unranked)."

        figures = collect_figures(tmp)

        payload: Dict[str, Any] = {
            "ok": bool(ok_pipeline),
            "trees": trees,
            "figures": figures or None,
            "annotations": [],
            "clones": {"clone_id": [], "seqs": []},  # schema compatibility with other methods
            "stats": stats,
            "logs": logs,
            "artifact_zip_b64": base64.b64encode(artifacts_zip).decode("ascii"),
            "artifact_name": "gctree_run_artifacts.zip",
            "render": "phylogeny" if figures else None,
        }

        if not ok_pipeline:
            # Show last failing step in error while still returning artifacts & logs
            last_fail = next(
                (L for L in reversed(logs) if not L.get("ok")), None
            )
            if last_fail:
                return JSONResponse(
                    status_code=400,
                    content={
                        **payload,
                        "ok": False,
                        "error": last_fail.get("out")
                        or f"Step {last_fail.get('step')} failed",
                    },
                )

        return ok(payload)

    finally:
        keep = os.getenv("KEEP_TMP") == "1"
        if keep:
            print(f"[gctree-bridge] keeping temp dir at: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


# Optional alias for dev parity
if not STRICT_CONTRACT_ROUTES:
    @app.post("/run")  # type: ignore
    async def _run_alias(request: Request):
        return await run_handler(request)
