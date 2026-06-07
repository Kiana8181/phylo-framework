# services/gctree/app.py
from __future__ import annotations

import base64
import io
import json
import os
import pickle
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from fastapi import FastAPI, Request
from dotenv import load_dotenv

load_dotenv()

from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# ---------- Constants & contracts ----------
METHOD_ID = "gctree"
CONTRACTS_DIR = Path(os.environ.get("CONTRACTS_DIR", "/contracts"))
METHOD_DIR = CONTRACTS_DIR / "methods" / METHOD_ID

SC_ALIGNED = "aligned_fasta_with_root"
SC_AIRR = "airr_or_changeo_table_adapter"
SC_DNAPARS = "dnapars_outfile_with_abundance"
SC_PICKLE = "gctree_forest_pickle"

SCENARIOS = {SC_ALIGNED, SC_AIRR, SC_DNAPARS, SC_PICKLE}

RESULT_GCTREE_RANKED = "gctree_ranked"
RESULT_RERENDER_PICKLE = "gctree_rerendered_from_pickle"
RESULT_FALLBACK_DNAPARS = "failed_gctree_infer_unranked_dnapars_available"
RESULT_FAILED = "failed"


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
    "text/fasta",
    "text/x-fasta",
    "text/csv",
    "text/tab-separated-values",
    "application/zip",
    "application/octet-stream",
]
DEFAULT_UI = {"requiresFile": True, "maxFiles": 1}

DEFAULT_ENV = {
    "QT_QPA_PLATFORM": "offscreen",
    "MPLBACKEND": "agg",
    "XDG_RUNTIME_DIR": "/tmp/runtime-gctree",
    "LC_ALL": "C",
    "LANG": "C",
}

RENDER_ERROR_PYQT_QTSVG = "ModuleNotFoundError: No module named 'PyQt5.QtSvg'"
RENDER_ERROR_ETE3_NODESTYLE = "AttributeError: module 'ete3' has no attribute 'NodeStyle'"

TREE_IMAGE_RE = re.compile(
    r"^.+\.inference\.(?P<rank>\d+)\.(?P<ext>svg|png|pdf)$", re.IGNORECASE
)
INFERENCE_AUX_IMAGE_RE = re.compile(
    r"^.+\.inference\.\d+\..+\.(svg|png|pdf)$", re.IGNORECASE
)

OUTBASE_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]")

# Ranking: only B, A, R — lexicographic B,A or linear B+0.01A style
RANKING_UNSAFE_RE = re.compile(r"[^BAR+0-9.,]")
RANKING_LEX_RE = re.compile(r"^[BAR](,[BAR])*$")
RANKING_LINEAR_TERM_RE = re.compile(r"^(?:\d+(?:\.\d+)?)?([BAR])$")

# FASTA validation
FASTA_LINE_DNA_RE = re.compile(r"^[ACGTURYSWKMBDHVNacgturyswkmbdhvn.\-]+$")
AMBIG_NT = set("NRYSWKMBDHVnryswkmbdhv")  # not counting 'n' separately
FASTA_HEADER_NUMERIC_RE = re.compile(r"^\d+$")

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


def err(msg: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"ok": False, "error": msg})


def _truthy(v: Any) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def safe_outbase(raw: str) -> str:
    """Safe basename for --outbase; rejects traversal and dot-only names.

    Examples:
      "../../bad" -> "bad"
      "..."       -> "gctree.out"
      ""          -> "gctree.out"
      "run 1"     -> "run_1"
    """
    cleaned = OUTBASE_SAFE_RE.sub("_", (raw or "").strip())
    cleaned = Path(cleaned).name
    cleaned = cleaned.strip("._")
    return cleaned or "gctree.out"


def validate_ranking(raw: Optional[str]) -> str:
    """Return canonical ranking string or raise ValueError."""
    s = (raw or "B,A").replace(" ", "").strip() or "B,A"
    if RANKING_UNSAFE_RE.search(s):
        raise ValueError(
            f"ranking_strategy contains unsupported characters or criteria: {raw!r}"
        )
    if RANKING_LEX_RE.match(s):
        return s
    if "," in s:
        raise ValueError(f"ranking_strategy mixes comma-lex form with other syntax: {raw!r}")
    if "+" not in s:
        raise ValueError(f"Invalid ranking_strategy: {raw!r}")
    parts = s.split("+")
    if any(p == "" for p in parts):
        raise ValueError(f"Invalid ranking_strategy (empty term): {raw!r}")
    for p in parts:
        m = RANKING_LINEAR_TERM_RE.match(p)
        if not m:
            raise ValueError(f"Invalid linear ranking term {p!r} in {raw!r}")
    return s


def _env(extra: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    env = os.environ.copy()
    env.update(DEFAULT_ENV)
    if extra:
        env.update(extra)
    try:
        rt_dir = Path(env["XDG_RUNTIME_DIR"])
        rt_dir.mkdir(parents=True, exist_ok=True)
        try:
            rt_dir.chmod(0o700)
        except Exception:
            pass
    except Exception:
        pass
    return env


def run_capture(
    cmd: List[str],
    cwd: Path,
    extra_env: Optional[Dict[str, str]] = None,
    use_shell: bool = False,
) -> Dict[str, Any]:
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
    env = _env(extra_env)
    if use_shell:
        proc = subprocess.Popen(
            " ".join(cmd),
            cwd=str(cwd),
            env=env,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    else:
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    stdout, stderr = proc.communicate()
    combined = (stdout or "") + (("\n[stderr]\n" + stderr) if stderr else "")
    logs.append(
        {
            "step": step_name,
            "cmd": " ".join(cmd),
            "ok": proc.returncode == 0,
            "out": combined,
        }
    )
    try:
        outfile.write_text(stdout or "", encoding="utf-8")
    except Exception as e:
        logs.append(
            {
                "step": f"{step_name}_write",
                "ok": False,
                "out": f"Failed to write {outfile.name}: {e}",
            }
        )
        return False
    return proc.returncode == 0


def parse_phylip_header(text: str) -> Optional[tuple[int, int, str]]:
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = re.match(r"^(\d+)\s+(\d+)(?:\s+.*)?$", line)
        if not m:
            continue
        try:
            ntax = int(m.group(1))
            nchar = int(m.group(2))
            return ntax, nchar, raw
        except Exception:
            continue
    return None


def detect_ext(filename: str, content_type: str | None) -> str:
    name = (filename or "").lower()
    ext = os.path.splitext(name)[1].lstrip(".")
    if ext:
        return ext
    if content_type and "fasta" in content_type.lower():
        return "fasta"
    if content_type and "zip" in content_type.lower():
        return "zip"
    if content_type and "octet-stream" in content_type.lower():
        return "bin"
    return "bin"


def read_text(p: Path) -> str:
    with p.open("r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def parse_fasta_records(path: Path) -> List[FastaRecord]:
    """Parse FASTA into ordered records.

    Concatenates sequence lines per record. Duplicate header IDs raise
    ValueError with a clear message (records are never silently overwritten).
    """
    text = read_text(path)
    ordered: List[FastaRecord] = []
    finalized: set[str] = set()

    cur_id: Optional[str] = None
    cur_buf: List[str] = []

    def finalize() -> None:
        nonlocal cur_id, cur_buf
        if cur_id is None:
            return
        seq = "".join(cur_buf)
        if not cur_id:
            raise ValueError("FASTA header line has an empty identifier after '>'.")
        if cur_id in finalized:
            raise ValueError(
                "Duplicate FASTA ID(s): each header after '>' must be unique. "
                f"Repeated ID {cur_id!r}."
            )
        finalized.add(cur_id)
        ordered.append(FastaRecord(original_id=cur_id, sequence=seq))
        cur_id = None
        cur_buf = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith(">"):
            finalize()
            cur_id = line[1:].strip().split()[0] if len(line) > 1 else ""
            cur_buf = []
        else:
            if cur_id is None:
                raise ValueError(
                    "FASTA sequence data appeared before the first header line ('>')."
                )
            cur_buf.append(line)

    finalize()
    return ordered


def is_gctree_safe_fasta_id(sid: str) -> bool:
    if not sid or len(sid) > 10:
        return False
    try:
        sid.encode("ascii")
    except UnicodeEncodeError:
        return False
    return FASTA_HEADER_NUMERIC_RE.fullmatch(sid) is None


def validate_fasta_record_ids(records_list: Sequence[FastaRecord]) -> Optional[str]:
    """Validate non-remappable FASTA ID constraints: non-empty and unique."""
    if not records_list:
        return "FASTA contains no sequences."

    seen: set[str] = set()
    for record in records_list:
        sid = record.original_id
        if not sid:
            return "FASTA header line has an empty identifier after '>'."
        if sid in seen:
            return (
                "Duplicate FASTA ID(s): each header after '>' must be unique. "
                f"Repeated ID {sid!r}."
            )
        seen.add(sid)
    return None


def _next_generated_safe_id(used: set[str], counter: int) -> Tuple[str, int]:
    while True:
        candidate = f"S{counter:06d}"
        counter += 1
        if candidate not in used:
            return candidate, counter


def _next_generated_safe_id_avoiding(
    used: set[str], reserved: set[str], counter: int
) -> Tuple[str, int]:
    while True:
        candidate, counter = _next_generated_safe_id(used, counter)
        if candidate not in reserved:
            return candidate, counter


def remap_fasta_ids_for_gctree(
    src: Path, dst: Path, root: str, map_path: Path
) -> FastaRemapResult:
    records_list = parse_fasta_records(src)
    id_err = validate_fasta_record_ids(records_list)
    if id_err:
        raise ValueError(id_err)

    original_ids = {record.original_id for record in records_list}
    if root not in original_ids:
        raise ValueError(
            f"Root sequence ID {root!r} not found among FASTA headers "
            f"(have {len(records_list)} validated IDs)."
        )

    root_safe = root if is_gctree_safe_fasta_id(root) else "GL"
    reserved_safe_ids = {
        record.original_id
        for record in records_list
        if is_gctree_safe_fasta_id(record.original_id)
    }
    used: set[str] = set()
    original_to_safe: Dict[str, str] = {}
    safe_to_original: Dict[str, str] = {}
    counter = 1

    root_record = next(record for record in records_list if record.original_id == root)
    original_to_safe[root_record.original_id] = root_safe
    safe_to_original[root_safe] = root_record.original_id
    used.add(root_safe)

    for record in records_list:
        original_id = record.original_id
        if original_id in original_to_safe:
            continue
        if is_gctree_safe_fasta_id(original_id) and original_id not in used:
            safe_id = original_id
        else:
            safe_id, counter = _next_generated_safe_id_avoiding(
                used, reserved_safe_ids, counter
            )
        original_to_safe[original_id] = safe_id
        safe_to_original[safe_id] = original_id
        used.add(safe_id)

    remapped_records: List[FastaRecord] = []
    for record in records_list:
        safe_id = original_to_safe[record.original_id]
        remapped_records.append(
            FastaRecord(original_id=safe_id, sequence=record.sequence)
        )

    remap_err = validate_gctree_safe_fasta_ids(remapped_records)
    if remap_err:
        raise ValueError(f"Internal FASTA ID remapping failed: {remap_err}")

    fasta_lines: List[str] = []
    for record in records_list:
        fasta_lines.append(f">{original_to_safe[record.original_id]}")
        fasta_lines.append(record.sequence)
    dst.write_text("\n".join(fasta_lines) + ("\n" if fasta_lines else ""), encoding="utf-8")

    map_lines = ["safe_id\toriginal_id"]
    for record in records_list:
        safe_id = original_to_safe[record.original_id]
        map_lines.append(f"{safe_id}\t{record.original_id}")
    map_path.write_text("\n".join(map_lines) + "\n", encoding="utf-8")

    remapped_count = sum(
        1
        for record in records_list
        if original_to_safe[record.original_id] != record.original_id
    )
    return FastaRemapResult(
        fasta_path=dst,
        original_to_safe=original_to_safe,
        safe_to_original=safe_to_original,
        effective_root=original_to_safe[root],
        remapped_count=remapped_count,
    )


def validate_gctree_safe_fasta_ids(records_list: Sequence[FastaRecord]) -> Optional[str]:
    if not records_list:
        return "FASTA contains no sequences."
    seen: set[str] = set()
    offenders: Dict[str, List[str]] = {}

    def add_issue(skey: str, reason: str) -> None:
        offenders.setdefault(skey, []).append(reason)

    for record in records_list:
        sid = record.original_id
        if not sid:
            add_issue("(empty)", "empty identifier after '>' header")
            continue
        if sid in seen:
            add_issue(sid, "duplicate identifier after remapping")
        seen.add(sid)
        if len(sid) > 10:
            add_issue(sid, f"too long (>10 PHYLIP characters; length {len(sid)})")
        try:
            sid.encode("ascii")
        except UnicodeEncodeError:
            add_issue(sid, "non-ASCII characters")
        if FASTA_HEADER_NUMERIC_RE.fullmatch(sid):
            add_issue(
                sid,
                "purely numeric IDs can clash with internal PHYLIP / DNAPARS node names",
            )

    if not offenders:
        return None

    lines = []
    for sid_key, rs in sorted(offenders.items(), key=lambda x: x[0]):
        uniq = sorted(set(rs))
        lines.append(f"  {sid_key!r}: " + "; ".join(uniq))
    return (
        "FASTA sequence IDs failed validation (must be unique, non-empty ASCII, "
        "at most 10 characters, not purely numeric). Issues:\n" + "\n".join(lines)
    )


def validate_fasta_for_gctree(
    path: Path, root: str
) -> Tuple[List[Any], Optional[str]]:
    """
    Biological / format checks before deduplicate (includes FASTA header rules).
    Returns (warnings, error_message_or_none).
    """
    warnings: List[Any] = []
    try:
        ordered = parse_fasta_records(path)
    except ValueError as e:
        return [], str(e)
    except Exception as e:
        return [], f"Failed to parse FASTA: {e}"

    id_err = validate_fasta_record_ids(ordered)
    if id_err:
        return warnings, id_err

    records: Dict[str, str] = {
        record.original_id: record.sequence for record in ordered
    }

    if root not in records:
        return (
            [],
            f"Root sequence ID {root!r} not found among FASTA headers "
            f"(have {len(records)} validated IDs).",
        )

    lens = {len(seq) for seq in records.values()}
    if len(lens) > 1:
        by_len: Dict[int, List[str]] = {}
        for sid, seq in records.items():
            by_len.setdefault(len(seq), []).append(sid)
        detail = "; ".join(f"len {L}: {ids[:5]}{'…' if len(ids)>5 else ''}" for L, ids in sorted(by_len.items()))
        return [], f"Sequences are not all the same aligned length: {detail}"

    alen = next(iter(lens))
    col_chars: List[set[str]] = [set() for _ in range(alen)]
    for seq in records.values():
        for i, ch in enumerate(seq):
            col_chars[i].add(ch.upper())

    variable_sites = sum(1 for s in col_chars if len({c for c in s if c not in ".-"}) > 1)

    ambig_positions = 0
    invalid_chars: List[str] = []
    for sid, seq in records.items():
        for ch in seq:
            cu = ch.upper()
            if not FASTA_LINE_DNA_RE.match(ch):
                if ch not in invalid_chars:
                    invalid_chars.append(ch)
            elif ch in AMBIG_NT or cu == "N":
                ambig_positions += 1

    if invalid_chars:
        return (
            [],
            "Invalid characters in sequence lines (allowed: nucleotide/IUPAC, gap, dot): "
            + ", ".join(repr(c) for c in invalid_chars[:12])
            + ("…" if len(invalid_chars) > 12 else ""),
        )

    if variable_sites == 0:
        warnings.append(
            {
                "code": "LOW_ALIGNMENT_VARIATION",
                "message": "No variable nucleotide sites detected; parsimony / GCtree may be degenerate.",
            }
        )
    elif variable_sites < max(3, alen // 100):
        warnings.append(
            {
                "code": "LOW_ALIGNMENT_VARIATION",
                "message": f"Very few variable sites ({variable_sites}); results may be unstable.",
            }
        )

    if ambig_positions > 0:
        warnings.append(
            {
                "code": "AMBIGUOUS_RESIDUES",
                "message": f"Alignment contains ambiguous/IUPAC or N residues ({ambig_positions} positions across sequences).",
            }
        )

    warnings.append(
        {
            "code": "SINGLE_CLONAL_FAMILY_ASSUMPTION",
            "message": "GCtree assumes a single clonal family / lineage; input should already be clone-filtered. "
            "FASTA alone does not prove a single lineage.",
        }
    )

    if len(records) != len({records[k] for k in records}):
        uniq_seq = len({records[k] for k in records})
        if uniq_seq < 3:
            warnings.append(
                {
                    "code": "LOW_UNIQUE_SEQUENCE_COUNT",
                    "message": f"Only {uniq_seq} unique sequence strings before deduplication; need ≥3 unique after deduplication.",
                }
            )

    return warnings, None


def normalize_fasta_sequence_lines(src: Path, dst: Path) -> Tuple[int, int]:
    """
    FASTA-only: replace '.' with '-' on sequence (non-header) lines only.
    Returns (chars_replaced, sequence_lines_touched).
    """
    chars_replaced = 0
    lines_touched = 0
    out_lines: List[str] = []
    for raw in src.read_text(encoding="utf-8", errors="ignore").splitlines(keepends=False):
        if raw.startswith(">"):
            out_lines.append(raw)
        else:
            if "." in raw:
                n = raw.count(".")
                chars_replaced += n
                lines_touched += 1
                raw = raw.replace(".", "-")
            out_lines.append(raw)
    dst.write_text("\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8")
    return chars_replaced, lines_touched


def safe_bundle_path(bundle_root: Path, relative: str) -> Path:
    bundle_root = bundle_root.resolve()
    rel_norm = relative.replace("\\", "/").lstrip("/")
    candidate = (bundle_root / rel_norm).resolve()
    candidate.relative_to(bundle_root)
    return candidate


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract ZIP members under dest only; reject path traversal."""
    dest = dest.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        for member in zf.infolist():
            target = (dest / member.filename).resolve()
            try:
                target.relative_to(dest)
            except ValueError as e:
                raise ValueError(f"Unsafe path in ZIP: {member.filename!r}") from e
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member) as src, target.open("wb") as out:
                    shutil.copyfileobj(src, out)


@dataclass(frozen=True)
class FastaRecord:
    original_id: str
    sequence: str


@dataclass(frozen=True)
class FastaRemapResult:
    fasta_path: Path
    original_to_safe: Dict[str, str]
    safe_to_original: Dict[str, str]
    effective_root: str
    remapped_count: int


@dataclass
class ZipBundle:
    unpack_root: Path
    scenario: str
    files: Dict[str, Path]


BUNDLE_ROLE_ARTIFACT_NAMES = {
    "dnapars_outfile": "bundle.dnapars_outfile",
    "abundances_csv": "bundle.abundances.csv",
    "idmapfile": "bundle.idmapfile",
    "positionmapfile": "bundle.positionmapfile",
    "positionmapfile2": "bundle.positionmapfile2",
    "isotype_mapfile": "bundle.isotype_mapfile",
    "idmapfile_isotype": "bundle.idmapfile_isotype",
    "gctree_forest_pickle": "bundle.gctree_forest_pickle.p",
    "aligned_fasta": "bundle.aligned_fasta.fasta",
}


def find_zip_bundle_manifest(unpack_dir: Path) -> Path:
    root_manifest = unpack_dir / "manifest.json"
    if root_manifest.is_file():
        return root_manifest

    candidates: List[Path] = []
    for child in sorted(unpack_dir.iterdir()):
        if not child.is_dir():
            continue
        if child.name == "__MACOSX" or child.name.startswith("."):
            continue
        manifest = child / "manifest.json"
        if manifest.is_file():
            candidates.append(manifest)

    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        rels = [str(p.relative_to(unpack_dir)) for p in candidates]
        raise ValueError(
            "ZIP bundle contains multiple manifest.json files; expected one at "
            f"the archive root or inside a single top-level folder. Found: {rels}"
        )
    raise ValueError(
        "ZIP bundle must contain manifest.json at the archive root or inside a "
        "single top-level bundle folder."
    )


def unpack_zip_bundle(zip_path: Path, tmp: Path, logs: List[dict]) -> ZipBundle:
    unpack_dir = tmp / "bundle_unpacked"
    unpack_dir.mkdir(parents=True, exist_ok=True)
    safe_extract_zip(zip_path, unpack_dir)
    manifest_path = find_zip_bundle_manifest(unpack_dir)
    bundle_root = manifest_path.parent
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    scenario = payload.get("scenario")
    if not isinstance(scenario, str) or scenario not in SCENARIOS:
        raise ValueError(
            f"manifest.json scenario must be one of {sorted(SCENARIOS)}, got {scenario!r}"
        )
    raw_files = payload.get("files")
    if not isinstance(raw_files, dict):
        raise ValueError("manifest.json 'files' must be an object mapping roles to filenames.")

    resolved: Dict[str, Path] = {}
    for role, fname in raw_files.items():
        if not isinstance(role, str) or not isinstance(fname, str):
            continue
        pth = safe_bundle_path(bundle_root, fname)
        if not pth.is_file():
            raise ValueError(f"Manifest file for role {role!r} not found: {fname!r}")
        resolved[role] = pth

    try:
        shutil.copy2(manifest_path, tmp / "manifest.json")
    except Exception:
        pass

    logs.append(
        {
            "step": "zip_bundle",
            "ok": True,
            "out": (
                f"Unpacked bundle scenario={scenario} "
                f"root={manifest_path.parent.relative_to(unpack_dir)!s} "
                f"roles={list(resolved.keys())}"
            ),
        }
    )
    return ZipBundle(unpack_root=bundle_root, scenario=scenario, files=resolved)


def preserve_bundle_role_artifacts(
    bundle: ZipBundle, tmp: Path, logs: List[dict]
) -> Dict[str, Path]:
    preserved: Dict[str, Path] = {}
    for role, artifact_name in BUNDLE_ROLE_ARTIFACT_NAMES.items():
        src = bundle.files.get(role)
        if not src or not src.is_file():
            continue
        dst = tmp / artifact_name
        try:
            shutil.copy2(src, dst)
            preserved[role] = dst
            logs.append(
                {
                    "step": "bundle_role_preserved",
                    "ok": True,
                    "out": f"Preserved manifest role {role!r} as {artifact_name}",
                }
            )
        except Exception as e:
            logs.append(
                {
                    "step": "bundle_role_preserved",
                    "ok": False,
                    "out": f"Could not preserve manifest role {role!r}: {e}",
                }
            )
    return preserved


def validate_manifest_roles(scenario: str, files: Mapping[str, Path]) -> None:
    if scenario in (SC_ALIGNED, SC_AIRR):
        if "aligned_fasta" not in files:
            raise ValueError(
                "ZIP manifest for aligned_fasta_with_root or airr_or_changeo_table_adapter "
                "must include role 'aligned_fasta'"
            )
    elif scenario == SC_DNAPARS:
        for req in ("dnapars_outfile", "abundances_csv"):
            if req not in files:
                raise ValueError(
                    f"Scenario {scenario} requires manifest role {req!r}"
                )
    elif scenario == SC_PICKLE:
        if "gctree_forest_pickle" not in files:
            raise ValueError(
                "Scenario gctree_forest_pickle requires manifest role 'gctree_forest_pickle'"
            )


def collect_newicks(outdir: Path, outbase: str, top_n: int) -> List[str]:
    pat = f"{outbase}.inference.*.nk"
    nks = sorted(outdir.glob(pat))
    out: List[str] = []
    for p in nks[:top_n]:
        try:
            out.append(read_text(p).strip())
        except Exception:
            pass
    return out


def extract_newicks_from_outtree(outtree_path: Path, limit: int = 10) -> List[str]:
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
                buf.append("".join(t.split()))
            cur = []
    seen = set()
    out: List[str] = []
    for t in buf:
        if t not in seen:
            out.append(t)
            seen.add(t)
        if len(out) >= limit:
            break
    return out


def zip_artifacts(outdir: Path, outbase: str) -> bytes:
    buf = io.BytesIO()
    patterns = [
        "outfile",
        "outtree",
        "dnapars.log",
        "dnapars.cfg",
        "deduplicated.phylip",
        "abundances.csv",
        "idmap.txt",
        "manifest.json",
        "original.*",
        "input_normalized.fasta",
        "input_gctree_safe.fasta",
        "fasta_idmap.tsv",
        "bundle.*",
        f"{outbase}.inference.*",
        f"{outbase}.*",
        "*.p",
        "*.nk",
        "*.svg",
        "*.png",
        "*.pdf",
        "*.log",
        "*.fasta",
        "*.fa",
        "*.csv",
        "*.tsv",
        "*.txt",
        "*.phylip",
        "*.cfg",
    ]
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
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


def _tree_rank_from_figure_name(name: str) -> Optional[int]:
    m = TREE_IMAGE_RE.match(name)
    if not m:
        return None
    try:
        return int(m.group("rank"))
    except Exception:
        return None


def _is_render_dependency_failure(log_output: str) -> bool:
    txt = str(log_output or "")
    return RENDER_ERROR_PYQT_QTSVG in txt or RENDER_ERROR_ETE3_NODESTYLE in txt


def collect_figures(outdir: Path) -> Dict[str, List[str]]:
    figs: Dict[str, List[str]] = {}
    phylogeny_ranked: List[Tuple[int, str]] = []
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
        name_lower = name.lower()
        tree_rank = _tree_rank_from_figure_name(name)
        if tree_rank is not None:
            mime = mime_by_ext[ext]
            phylogeny_ranked.append((tree_rank, f"data:{mime};base64,{b64}"))
            continue

        if "abundance_rank" in name_lower:
            key = "abundance_rank"
        elif ".tree_stats." in name_lower or "tree_stats" in name_lower or "pairplot" in name_lower:
            key = "tree_stats"
        elif INFERENCE_AUX_IMAGE_RE.match(name):
            key = "method_charts"
        else:
            key = "other_outputs"

        mime = mime_by_ext[ext]
        figs.setdefault(key, []).append(f"data:{mime};base64,{b64}")

    if phylogeny_ranked:
        figs["phylogeny"] = [data for _, data in sorted(phylogeny_ranked, key=lambda x: x[0])]

    return figs


def parse_abundances_csv(path: Path) -> Dict[str, float]:
    out: Dict[str, float] = {}
    if not path.exists():
        return out
    try:
        rows = path.read_text(errors="ignore").splitlines()
    except Exception:
        return out
    for raw in rows:
        line = raw.strip()
        if not line:
            continue
        parts = [p for p in re.split(r"[\t,]+", line) if p != ""]
        if len(parts) < 2:
            continue
        label = parts[0].strip()
        if not label:
            continue
        try:
            value = float(parts[1])
        except Exception:
            continue
        if value < 0:
            continue
        out[label] = value
    return out


def parse_idmap(path: Path) -> Dict[str, str]:
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    try:
        rows = path.read_text(errors="ignore").splitlines()
    except Exception:
        return out
    for raw in rows:
        line = raw.strip()
        if not line:
            continue
        parts = [p for p in re.split(r"[\t, ]+", line) if p]
        if len(parts) < 2:
            continue
        key = parts[0].strip()
        val = parts[1].strip()
        if key and val:
            out[key] = val
    return out


def parse_fasta_idmap(path: Path) -> Dict[str, str]:
    """Parse fasta_idmap.tsv as safe_id -> original_id."""
    out: Dict[str, str] = {}
    if not path.exists():
        return out
    try:
        rows = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return out
    for raw in rows:
        line = raw.strip()
        if not line:
            continue
        parts = line.split("\t", 1)
        if len(parts) < 2:
            parts = [p for p in re.split(r"[\t, ]+", line, maxsplit=1) if p]
        if len(parts) < 2:
            continue
        safe_id = parts[0].strip()
        original_id = parts[1].strip()
        if safe_id.lower() == "safe_id" and original_id.lower() == "original_id":
            continue
        if safe_id and original_id:
            out[safe_id] = original_id
    return out


def bridge_deduplicate_idmap_to_original(
    dedup_idmap: Path, fasta_idmap: Path, output: Path
) -> Tuple[bool, int, List[str]]:
    dedup_to_safe = parse_idmap(dedup_idmap)
    safe_to_original = parse_fasta_idmap(fasta_idmap)
    if not dedup_to_safe or not safe_to_original:
        return False, 0, []

    bridged_count = 0
    unmapped_safe_ids: List[str] = []
    out_lines: List[str] = []
    seen_unmapped: set[str] = set()
    for label, safe_id in dedup_to_safe.items():
        original_id = safe_to_original.get(safe_id)
        if original_id is None:
            original_id = safe_id
            if safe_id not in seen_unmapped:
                unmapped_safe_ids.append(safe_id)
                seen_unmapped.add(safe_id)
        else:
            bridged_count += 1
        out_lines.append(f"{label}\t{original_id}")

    output.write_text(
        "\n".join(out_lines) + ("\n" if out_lines else ""), encoding="utf-8"
    )
    return True, bridged_count, unmapped_safe_ids


def _base_payload(
    *,
    ok: bool,
    trees: List[str],
    figures: Optional[Dict[str, List[str]]],
    logs: List[dict],
    tmp: Path,
    outbase: str,
    abund_csv: Path,
    idmap_txt: Path,
    warnings: List[Any],
    render_meta: Dict[str, Any],
    stats: Dict[str, Any],
    error: Optional[str] = None,
    status_code: int = 200,
    response_idmap_path: Optional[Path] = None,
) -> JSONResponse:
    artifacts_zip = zip_artifacts(tmp, outbase)
    node_abundances = parse_abundances_csv(abund_csv)
    label_to_sequence_id = parse_idmap(response_idmap_path or idmap_txt)
    payload: Dict[str, Any] = {
        "ok": ok,
        "trees": trees,
        "figures": figures or None,
        "annotations": [],
        "clones": {"clone_id": [], "seqs": []},
        "node_abundances": node_abundances or None,
        "label_to_sequence_id": label_to_sequence_id or None,
        "stats": stats,
        "logs": logs,
        "warnings": warnings,
        "render_meta": render_meta,
        "artifact_zip_b64": base64.b64encode(artifacts_zip).decode("ascii"),
        "artifact_name": "gctree_run_artifacts.zip",
        "render": "phylogeny" if (figures and figures.get("phylogeny")) else None,
        "tree_model": "phylogeny",
    }
    if error:
        payload["error"] = error
    return JSONResponse(status_code=status_code, content=payload)


def early_fail(
    msg: str,
    logs: List[dict],
    tmp: Path,
    *,
    outbase: str = "gctree.out",
    input_scenario: str = SC_ALIGNED,
    result_quality: str = RESULT_FAILED,
    warnings: Optional[List[Any]] = None,
    render_meta: Optional[Dict[str, Any]] = None,
) -> JSONResponse:
    w = list(warnings or [])
    w.append({"code": "RUN_FAILED", "message": msg})
    rm = dict(render_meta or {})
    stats_block: Dict[str, Any] = {
        "input_scenario": input_scenario,
        "result_quality": result_quality,
        "n_trees_found": 0,
    }
    return _base_payload(
        ok=False,
        trees=[],
        figures=collect_figures(tmp),
        logs=logs,
        tmp=tmp,
        outbase=outbase,
        abund_csv=tmp / "abundances.csv",
        idmap_txt=tmp / "idmap.txt",
        warnings=w,
        render_meta=rm,
        stats=stats_block,
        error=msg,
        status_code=400,
        response_idmap_path=tmp / "idmap.txt",
    )


def render_colored_phylogeny_from_pickle(
    tmp: Path,
    outbase: str,
    color_mode: str,
    logs: List[dict],
) -> Tuple[Optional[str], Dict[str, Any], List[Any]]:
    """Fixed viridis + abundance (linear) or LBI (log, falling back when needed).

    Returns (data_url, meta, extra_warnings). extra_warnings attach to HTTP payload.
    """
    extra_warnings: List[Any] = []
    meta: Dict[str, Any] = {
        "enabled": False,
        "mode": (color_mode or "none").lower(),
        "feature": None,
        "palette": "viridis",
        "requested_scale": None,
        "effective_scale": None,
        "scale_fallback_reason": None,
        "vmin": None,
        "vmax": None,
        "colored_tree_rank": 1,
        "missing_value_count": 0,
        "invalid_value_count": 0,
    }

    mode = (color_mode or "none").lower()
    if not mode or mode in ("none", "off", "disabled"):
        logs.append({"step": "coloring_skip", "ok": True, "out": "Coloring disabled."})
        return None, meta, extra_warnings

    try:
        import gctree  # type: ignore  # noqa: F401
    except Exception as e:
        logs.append(
            {
                "step": "coloring_import",
                "ok": False,
                "out": f"Could not import gctree Python API: {e}",
            }
        )
        meta["error"] = str(e)
        return None, meta, extra_warnings

    p_files = sorted(tmp.glob(f"{outbase}.inference.*.p"))
    if not p_files:
        logs.append(
            {
                "step": "coloring_no_pickle",
                "ok": False,
                "out": f"No {outbase}.inference.*.p for coloring.",
            }
        )
        return None, meta, extra_warnings

    p_path = p_files[0]
    meta["colored_tree_rank"] = 1
    mrank = re.search(r"\.inference\.(\d+)\.", p_path.name)
    if mrank:
        try:
            meta["colored_tree_rank"] = int(mrank.group(1))
        except Exception:
            pass

    try:
        with p_path.open("rb") as fh:
            tree_obj = pickle.load(fh)
    except Exception as e:
        logs.append(
            {"step": "coloring_load_pickle", "ok": False, "out": str(e)}
        )
        meta["error"] = str(e)
        return None, meta, extra_warnings

    try:
        if hasattr(tree_obj, "feature_colormap"):
            tree = tree_obj
        elif hasattr(tree_obj, "sample_tree"):
            tree = tree_obj.sample_tree()
            logs.append(
                {
                    "step": "coloring_sample_tree",
                    "ok": True,
                    "out": "Sampled tree from forest pickle for coloring.",
                }
            )
        else:
            logs.append(
                {
                    "step": "coloring_unsupported_pickle",
                    "ok": False,
                    "out": f"Unsupported pickle type {type(tree_obj).__name__}",
                }
            )
            return None, meta, extra_warnings
    except Exception as e:
        logs.append({"step": "coloring_normalize_tree", "ok": False, "out": str(e)})
        return None, meta, extra_warnings

    feature: Optional[str] = None
    requested_scale = "linear"
    effective_scale = "linear"

    if mode == "abundance":
        feature = "abundance"
        requested_scale = "linear"
        effective_scale = "linear"
    elif mode == "lbi":
        try:
            tree.local_branching()
        except Exception as e:
            logs.append({"step": "coloring_lbi", "ok": False, "out": str(e)})
            meta["error"] = str(e)
            return None, meta, extra_warnings
        feature = "LBI"
        requested_scale = "log"
        effective_scale = "log"
    else:
        logs.append({"step": "coloring_unknown_mode", "ok": False, "out": mode})
        return None, meta, extra_warnings

    meta["enabled"] = True
    meta["feature"] = feature
    meta["requested_scale"] = requested_scale
    meta["effective_scale"] = effective_scale

    values: List[float] = []
    missing = 0
    invalid = 0
    try:
        for node in tree.traverse():  # type: ignore[attr-defined]
            raw = getattr(node, feature, None)
            if raw is None:
                missing += 1
                continue
            try:
                fv = float(raw)
            except Exception:
                invalid += 1
                continue
            if fv != fv:  # NaN
                invalid += 1
                continue
            values.append(fv)
    except Exception as e:
        logs.append({"step": "coloring_feature_scan", "ok": False, "out": str(e)})
        meta["error"] = str(e)
        return None, meta, extra_warnings

    if values:
        meta["vmin"] = min(values)
        meta["vmax"] = max(values)

    meta["missing_value_count"] = missing
    meta["invalid_value_count"] = invalid

    if (
        feature == "LBI"
        and requested_scale == "log"
        and values
        and min(values) <= 0
    ):
        effective_scale = "linear"
        meta["effective_scale"] = "linear"
        meta["scale_fallback_reason"] = "LBI contains non-positive values; log scale is undefined."
        fb_msg = (
            "LBI contained non-positive values; log coloring was replaced with linear coloring."
        )
        extra_warnings.append({"code": "COLORING_LBI_LOG_FALLBACK", "message": fb_msg})
        logs.append({"step": "coloring_lbi_scale_fallback", "ok": True, "out": fb_msg})

    cmap_name = "viridis"
    try:
        colormap = tree.feature_colormap(feature, cmap=cmap_name, scale=effective_scale)
    except Exception as e:
        logs.append(
            {"step": "coloring_colormap_failed", "ok": False, "out": str(e)}
        )
        meta["error"] = str(e)
        return None, meta, extra_warnings

    colored_svg_path = tmp / f"{outbase}.colored.phylogeny.svg"
    try:
        tree.render(str(colored_svg_path), colormap=colormap)
    except Exception as e:
        logs.append({"step": "coloring_render", "ok": False, "out": str(e)})
        meta["error"] = str(e)
        return None, meta, extra_warnings

    svg_bytes = colored_svg_path.read_bytes()
    b64 = base64.b64encode(svg_bytes).decode("ascii")
    data_url = f"data:image/svg+xml;base64,{b64}"
    logs.append(
        {
            "step": "coloring_render",
            "ok": True,
            "out": f"Colored phylogeny feature={feature} scale={effective_scale}.",
        }
    )
    return data_url, meta, extra_warnings


def append_infer_options(
    cmd: List[str],
    params: Mapping[str, Any],
    *,
    positionmap: Optional[Path] = None,
    positionmap2: Optional[Path] = None,
) -> None:
    cs = params.get("chain_split")
    try:
        cs_i = int(cs) if cs is not None else 0
    except Exception:
        cs_i = 0
    if cs_i > 0:
        cmd.extend(["--chain_split", str(cs_i)])

    if "frame2" in params and params.get("frame2") is not None:
        try:
            f2i = int(params["frame2"])
            if f2i in (1, 2, 3):
                cmd.extend(["--frame2", str(f2i)])
        except Exception:
            pass

    if positionmap and positionmap.is_file():
        cmd.extend(["--positionmapfile", str(positionmap)])
    if positionmap2 and positionmap2.is_file():
        cmd.extend(["--positionmapfile2", str(positionmap2)])


def run_isotype_step(
    tmp: Path,
    logs: List[dict],
    idmap_path: Path,
    isotype_map_path: Path,
    tree_pickles: Sequence[Path],
) -> Dict[str, Any]:
    meta: Dict[str, Any] = {"applied": False, "artifacts": []}
    if not tree_pickles:
        logs.append({"step": "isotype_skip", "ok": True, "out": "No tree pickles for isotype."})
        return meta
    cmd: List[str] = [
        "gctree",
        "isotype",
        str(idmap_path),
        str(isotype_map_path),
        "--trees",
    ]
    cmd.extend(str(p) for p in tree_pickles)
    step = run_capture(cmd, cwd=tmp)
    logs.append({**step, "step": "gctree_isotype"})
    if step["ok"]:
        meta["applied"] = True
        meta["artifacts"] = [p.name for p in tmp.iterdir() if p.is_file() and "isotype" in p.name.lower()]
    return meta


def select_effective_isotype_idmap(
    uploaded_idmap: Optional[Path],
    bridged_original_idmap: Optional[Path],
    fallback_idmap: Path,
    fallback_source: str,
) -> Tuple[Optional[Path], str]:
    if uploaded_idmap and uploaded_idmap.is_file():
        return uploaded_idmap, "uploaded_idmapfile_isotype"
    if (
        bridged_original_idmap
        and bridged_original_idmap.is_file()
        and bridged_original_idmap.stat().st_size > 0
    ):
        return bridged_original_idmap, "bridged_original_idmap"
    if fallback_idmap.is_file() and fallback_idmap.stat().st_size > 0:
        return fallback_idmap, fallback_source
    return None, "missing"


def _parse_frame(params: Mapping[str, Any]) -> str:
    try:
        frame = int(params.get("frame", 1))
    except Exception:
        frame = 1
    if frame not in (1, 2, 3):
        frame = 1
    return str(frame)


def extend_infer_cmd_base(
    cmd: List[str],
    *,
    root: str,
    frame_s: str,
    ranking: str,
    outbase: str,
    img_type: str,
    idlabel: bool,
    show_mut: bool,
    summarize_forest: bool,
    tree_stats: bool,
    params: Mapping[str, Any],
    positionmap: Optional[Path],
    positionmap2: Optional[Path],
) -> None:
    cmd.extend(
        [
            "--root",
            root,
            "--frame",
            frame_s,
            "--ranking_strategy",
            ranking,
            "--outbase",
            outbase,
            "--img_type",
            img_type,
            "--verbose",
        ]
    )
    if idlabel:
        cmd.append("--idlabel")
    if show_mut:
        cmd.append("--show_nucleotide_mutations")
    if summarize_forest:
        cmd.append("--summarize_forest")
    if tree_stats:
        cmd.append("--tree_stats")
    append_infer_options(cmd, params, positionmap=positionmap, positionmap2=positionmap2)


# ---------- Handlers ----------
@app.get(ROUTES["spec"])
def spec_handler():
    try:
        try:
            import gctree as _g  # noqa
            pkg_ver = getattr(_g, "__version__", "unknown")
        except Exception:
            pkg_ver = "unknown"

        param_schema = _read_json(
            PARAM_SCHEMA_PATH,
            {"type": "object", "properties": {}, "required": ["input_scenario"]},
        )

        from_spec = _read_json(SPEC_JSON_PATH, {})
        ui_hints = {**DEFAULT_UI, **(UI_JSON or {})}

        return ok(
            {
                "id": METHOD_ID,
                "name": from_spec.get("name") or "GCtree (bridge)",
                "version": from_spec.get("version") or pkg_ver,
                "accepts": from_spec.get("accepts") or DEFAULT_ACCEPTS,
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
    warnings: List[Any] = []
    render_meta: Dict[str, Any] = {}
    fallback_trees: List[str] = []
    input_scenario = SC_ALIGNED
    outbase_safe = safe_outbase("gctree.out")

    try:
        ct = (request.headers.get("content-type") or "").lower()

        if "application/json" in ct:
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
            path_in = tmp / fname
            try:
                shutil.copy2(src, path_in)
            except Exception:
                path_in.write_bytes(src.read_bytes())

            ext = detect_ext(fname, None)

        else:
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
                return err("file is required")

            raw = await upload.read()
            fname = getattr(upload, "filename", None) or "upload.bin"
            path_in = tmp / fname
            path_in.write_bytes(raw)
            ext = detect_ext(fname, getattr(upload, "content_type", None))

        input_scenario = str(p.get("input_scenario") or SC_ALIGNED).strip()
        if input_scenario not in SCENARIOS:
            return early_fail(
                f"Invalid input_scenario {input_scenario!r}",
                logs,
                tmp,
                input_scenario=input_scenario,
                warnings=warnings,
            )

        try:
            ranking = validate_ranking(p.get("ranking_strategy"))
        except ValueError as e:
            warnings.append({"code": "RANKING_INVALID", "message": str(e)})
            return early_fail(
                str(e),
                logs,
                tmp,
                input_scenario=input_scenario,
                warnings=warnings,
            )

        outbase_safe = safe_outbase(str(p.get("outbase") or "gctree.out"))
        top_n = int(p.get("top_n") or 3)
        top_n = max(1, min(10, top_n))

        frame_s = _parse_frame(p)

        quick = _truthy(p.get("quick") or False)
        jumble = p.get("jumble")
        idlabel = _truthy(p.get("idlabel") or False)
        show_mut = _truthy(p.get("show_nucleotide_mutations") or False)
        summarize_forest = _truthy(p.get("summarize_forest") or False)
        tree_stats = _truthy(p.get("tree_stats") or False)
        img_type = (p.get("img_type") or "svg").strip().lower()
        apply_coloring = _truthy(p.get("apply_coloring_settings")) and str(
            p.get("color_mode") or "none"
        ).lower() not in ("none", "", "off")
        color_mode = (p.get("color_mode") or "none").lower()
        if not apply_coloring:
            color_mode = "none"

        apply_isotype = _truthy(p.get("apply_isotype"))

        root = str(p.get("root") or "GL").strip() or "GL"

        dedup_phylip = tmp / "deduplicated.phylip"
        abund_csv = tmp / "abundances.csv"
        idmap_txt = tmp / "idmap.txt"
        dnapars_cfg = tmp / "dnapars.cfg"
        outfile = tmp / "outfile"
        outtree = tmp / "outtree"

        zip_bundle: Optional[ZipBundle] = None
        positionmap_path: Optional[Path] = None
        positionmap_path2: Optional[Path] = None
        isotype_idmap: Optional[Path] = None
        isotype_map: Optional[Path] = None
        generated_or_bundle_idmap_source = "missing"
        original_root = root
        effective_root = root
        fasta_remapped_count = 0
        fasta_idmap_artifact: Optional[str] = None
        response_idmap_path = idmap_txt
        bridged_original_idmap: Optional[Path] = None

        # ----- ZIP bundle scenarios -----
        if ext == "zip":
            try:
                zip_bundle = unpack_zip_bundle(path_in, tmp, logs)
            except Exception as e:
                return early_fail(
                    f"Invalid ZIP bundle: {e}",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            if zip_bundle.scenario != input_scenario:
                return early_fail(
                    f"params.input_scenario ({input_scenario}) does not match manifest scenario ({zip_bundle.scenario})",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            try:
                validate_manifest_roles(zip_bundle.scenario, zip_bundle.files)
            except ValueError as e:
                return early_fail(
                    str(e),
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            preserve_bundle_role_artifacts(zip_bundle, tmp, logs)
            input_scenario = zip_bundle.scenario
            positionmap_path = zip_bundle.files.get("positionmapfile")
            positionmap_path2 = zip_bundle.files.get("positionmapfile2")
            isotype_idmap = zip_bundle.files.get("idmapfile_isotype")
            isotype_map = zip_bundle.files.get("isotype_mapfile")
            if input_scenario in (SC_ALIGNED, SC_AIRR):
                af = zip_bundle.files.get("aligned_fasta")
                path_in = af
                ext = "fasta"

        elif input_scenario in (SC_DNAPARS, SC_PICKLE) and ext != "zip":
            # single-file pickle path
            if input_scenario == SC_DNAPARS:
                return early_fail(
                    "Scenario dnapars_outfile_with_abundance requires a .zip bundle with manifest.json",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

        infer_ok = False
        used_fallback_trees = False
        gctree_nk_trees: List[str] = []
        result_quality = RESULT_FAILED

        # ----- Scenario: pickle (single .p upload) -----
        if input_scenario == SC_PICKLE and ext != "zip":
            if ext not in ("p", "pickle", "bin"):
                return early_fail(
                    "gctree_forest_pickle requires a .p pickle or a ZIP bundle",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            infer_cmd: List[str] = [
                "gctree",
                "infer",
                str(path_in),
            ]
            extend_infer_cmd_base(
                infer_cmd,
                root=root,
                frame_s=frame_s,
                ranking=ranking,
                outbase=outbase_safe,
                img_type=img_type,
                idlabel=idlabel,
                show_mut=show_mut,
                summarize_forest=summarize_forest,
                tree_stats=tree_stats,
                params=p,
                positionmap=positionmap_path,
                positionmap2=positionmap_path2,
            )
            step = run_capture(infer_cmd, cwd=tmp)
            logs.append({**step, "step": "gctree_infer"})
            infer_ok = bool(step["ok"])
            if not infer_ok and _is_render_dependency_failure(step.get("out", "")):
                logs.append(
                    {
                        "step": "gctree_infer_note",
                        "ok": False,
                        "out": "Possible GCtree render dependency failure; see logs.",
                    }
                )
            gctree_nk_trees = collect_newicks(tmp, outbase_safe, top_n)
            result_quality = (
                RESULT_RERENDER_PICKLE if infer_ok else RESULT_FAILED
            )

        elif input_scenario == SC_PICKLE and zip_bundle is not None:
            pk_path = zip_bundle.files["gctree_forest_pickle"]
            infer_cmd = ["gctree", "infer", str(pk_path)]
            extend_infer_cmd_base(
                infer_cmd,
                root=root,
                frame_s=frame_s,
                ranking=ranking,
                outbase=outbase_safe,
                img_type=img_type,
                idlabel=idlabel,
                show_mut=show_mut,
                summarize_forest=summarize_forest,
                tree_stats=tree_stats,
                params=p,
                positionmap=positionmap_path,
                positionmap2=positionmap_path2,
            )
            step = run_capture(infer_cmd, cwd=tmp)
            logs.append({**step, "step": "gctree_infer"})
            infer_ok = bool(step["ok"])
            gctree_nk_trees = collect_newicks(tmp, outbase_safe, top_n)
            result_quality = (
                RESULT_RERENDER_PICKLE if infer_ok else RESULT_FAILED
            )

        elif input_scenario == SC_DNAPARS and zip_bundle is not None:
            od = zip_bundle.files["dnapars_outfile"]
            ab = zip_bundle.files["abundances_csv"]
            try:
                shutil.copy2(od, outfile)
                shutil.copy2(ab, abund_csv)
                logs.append(
                    {
                        "step": "dnapars_bundle_inputs_copied",
                        "ok": True,
                        "out": "Copied manifest dnapars_outfile to outfile and abundances_csv to abundances.csv",
                    }
                )
            except Exception as e:
                return early_fail(
                    f"Could not copy DNAPARS bundle inputs to standard artifact names: {e}",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            opt_idmap = zip_bundle.files.get("idmapfile")
            if opt_idmap and opt_idmap.is_file():
                try:
                    shutil.copy2(opt_idmap, idmap_txt)
                    generated_or_bundle_idmap_source = "bundle_idmapfile"
                    logs.append(
                        {
                            "step": "dnapars_idmap_copied",
                            "ok": True,
                            "out": f"Copied manifest idmapfile to {idmap_txt.name}",
                        }
                    )
                except Exception as e:
                    logs.append(
                        {
                            "step": "dnapars_idmap_copied",
                            "ok": False,
                            "out": str(e),
                        }
                    )
            infer_cmd = ["gctree", "infer", "outfile", "abundances.csv"]
            extend_infer_cmd_base(
                infer_cmd,
                root=root,
                frame_s=frame_s,
                ranking=ranking,
                outbase=outbase_safe,
                img_type=img_type,
                idlabel=idlabel,
                show_mut=show_mut,
                summarize_forest=summarize_forest,
                tree_stats=tree_stats,
                params=p,
                positionmap=positionmap_path,
                positionmap2=positionmap_path2,
            )
            if idmap_txt.is_file() and idmap_txt.stat().st_size > 0:
                infer_cmd.extend(["--idmapfile", "idmap.txt"])
            step = run_capture(infer_cmd, cwd=tmp)
            logs.append({**step, "step": "gctree_infer"})
            infer_ok = bool(step["ok"])
            gctree_nk_trees = collect_newicks(tmp, outbase_safe, top_n)
            result_quality = RESULT_GCTREE_RANKED if infer_ok else RESULT_FAILED

        else:
            # ----- FASTA-derived (aligned + airr adapter) -----
            if input_scenario == SC_AIRR:
                warnings.append(
                    {
                        "code": "TABULAR_ADAPTER",
                        "message": "airr_or_changeo_table_adapter: table was converted to aligned FASTA by the framework; GCtree is not run directly on AIRR/Change-O.",
                    }
                )

            if ext in ("csv", "tsv", "tabular"):
                return early_fail(
                    "Expected aligned FASTA after preprocessing; got tabular extension. "
                    "Ensure API preprocess converted the upload.",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            if ext not in ("fa", "fasta", "fas", "fna"):
                return early_fail(
                    f"Unsupported input extension {ext!r} for scenario {input_scenario}",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            orig_dst = tmp / f"original.{ext}"
            try:
                shutil.copy2(path_in, orig_dst)
            except Exception:
                orig_dst.write_bytes(path_in.read_bytes())

            fasta_norm = tmp / "input_normalized.fasta"
            try:
                n_dot, n_lines = normalize_fasta_sequence_lines(path_in, fasta_norm)
            except Exception as e:
                return early_fail(
                    f"FASTA normalization failed: {e}",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            logs.append(
                {
                    "step": "fasta_normalize",
                    "ok": True,
                    "out": f"Dot-to-gap on sequence lines only: {n_dot} characters in {n_lines} lines.",
                }
            )
            if n_dot > 0:
                warnings.append(
                    {
                        "code": "FASTA_DOT_TO_GAP_APPLIED",
                        "message": f"Replaced {n_dot} '.' characters with '-' on sequence lines; original preserved as {orig_dst.name}.",
                    }
                )

            bio_w, bio_err = validate_fasta_for_gctree(fasta_norm, root)
            warnings.extend(bio_w)
            if bio_err:
                return early_fail(
                    bio_err,
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            fasta_safe = tmp / "input_gctree_safe.fasta"
            fasta_idmap = tmp / "fasta_idmap.tsv"
            try:
                remap_result = remap_fasta_ids_for_gctree(
                    fasta_norm, fasta_safe, root, fasta_idmap
                )
                remapped_records = parse_fasta_records(remap_result.fasta_path)
                remap_err = validate_gctree_safe_fasta_ids(remapped_records)
                if remap_err:
                    raise ValueError(remap_err)
            except Exception as e:
                return early_fail(
                    f"FASTA ID remapping failed: {e}",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            effective_root = remap_result.effective_root
            fasta_remapped_count = remap_result.remapped_count
            fasta_idmap_artifact = fasta_idmap.name
            render_meta["fasta_id_remap"] = {
                "remapped_count": fasta_remapped_count,
                "mapping_file": fasta_idmap.name,
                "original_root": root,
                "effective_root": effective_root,
            }
            logs.append(
                {
                    "step": "fasta_id_remap",
                    "ok": True,
                    "out": (
                        f"Remapped {fasta_remapped_count} FASTA ID(s) for PHYLIP/GCtree compatibility; "
                        f"root {root!r} -> {effective_root!r}; mapping={fasta_idmap.name}."
                    ),
                }
            )
            if fasta_remapped_count > 0:
                warnings.append(
                    {
                        "code": "FASTA_IDS_REMAPPED",
                        "message": (
                            f"Remapped {fasta_remapped_count} FASTA ID(s) to short ASCII IDs for "
                            f"PHYLIP/GCtree compatibility. Original-to-safe mapping is in {fasta_idmap.name}."
                        ),
                    }
                )

            ok1 = run_to_file(
                [
                    "deduplicate",
                    str(remap_result.fasta_path),
                    "--root",
                    effective_root,
                    "--frame",
                    frame_s,
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
                return early_fail(
                    "deduplicate failed — see logs",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            if idmap_txt.is_file() and idmap_txt.stat().st_size > 0:
                generated_or_bundle_idmap_source = "generated_deduplicate_idmap.txt"
                idmap_original = tmp / "idmap.original.tsv"
                try:
                    bridged_ok, bridged_count, unmapped_safe_ids = (
                        bridge_deduplicate_idmap_to_original(
                            idmap_txt, fasta_idmap, idmap_original
                        )
                    )
                except Exception as e:
                    bridged_ok = False
                    bridged_count = 0
                    unmapped_safe_ids = []
                    logs.append(
                        {
                            "step": "idmap_original_bridge",
                            "ok": False,
                            "out": f"Could not create {idmap_original.name}: {e}",
                        }
                    )
                if bridged_ok:
                    response_idmap_path = idmap_original
                    bridged_original_idmap = idmap_original
                    logs.append(
                        {
                            "step": "idmap_original_bridge",
                            "ok": True,
                            "out": (
                                f"Created {idmap_original.name} with {bridged_count} bridged "
                                f"entry(ies) from {idmap_txt.name} using {fasta_idmap.name}."
                            ),
                        }
                    )
                    if unmapped_safe_ids:
                        logs.append(
                            {
                                "step": "idmap_original_bridge_unmapped",
                                "ok": True,
                                "out": (
                                    "Safe ID(s) not found in fasta_idmap.tsv and kept unchanged: "
                                    + ", ".join(unmapped_safe_ids[:20])
                                    + ("..." if len(unmapped_safe_ids) > 20 else "")
                                ),
                            }
                        )
                        warnings.append(
                            {
                                "code": "FASTA_IDMAP_PARTIAL_BRIDGE",
                                "message": (
                                    f"{len(unmapped_safe_ids)} safe ID(s) from idmap.txt were not found "
                                    f"in {fasta_idmap.name}; those response idmap values were kept unchanged."
                                ),
                            }
                        )
                else:
                    logs.append(
                        {
                            "step": "idmap_original_bridge",
                            "ok": False,
                            "out": (
                                f"Did not create {idmap_original.name}; missing or empty "
                                f"{idmap_txt.name} or {fasta_idmap.name}."
                            ),
                        }
                    )

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

            mkconfig_cmd.extend([str(dedup_phylip), "dnapars"])
            ok2 = run_to_file(
                mkconfig_cmd,
                cwd=tmp,
                outfile=dnapars_cfg,
                logs=logs,
                step_name="mkconfig",
            )
            if not ok2:
                return early_fail(
                    "mkconfig failed — see logs",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            dedup_text = dedup_phylip.read_text(errors="ignore")
            parsed_hdr = parse_phylip_header(dedup_text)
            if parsed_hdr is None:
                preview = "\n".join(dedup_text.splitlines()[:10])
                logs.append(
                    {
                        "step": "phylip_header",
                        "ok": False,
                        "out": "Could not parse header. First lines:\n" + preview,
                    }
                )
                return early_fail(
                    "Could not parse PHYLIP header from deduplicated.phylip",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            ntax, nchar, raw_hdr = parsed_hdr
            logs.append(
                {
                    "step": "phylip_header",
                    "ok": True,
                    "out": f"Ntax={ntax} Nchar={nchar}; header={raw_hdr!r}",
                }
            )

            if ntax < 3:
                return early_fail(
                    (
                        "After deduplication there are fewer than three unique sequences (Ntax="
                        f"{ntax}). GCtree / DNAPARS need at least three unique sequences with some variation."
                    ),
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )
            if nchar < 1:
                return early_fail(
                    "Alignment has 0 columns after deduplication.",
                    logs,
                    tmp,
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

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
                    outbase=outbase_safe,
                    input_scenario=input_scenario,
                    warnings=warnings,
                )

            fallback_trees = extract_newicks_from_outtree(
                outtree, limit=max(1, top_n)
            )

            infer_cmd = [
                "gctree",
                "infer",
                "outfile",
                str(abund_csv),
            ]
            extend_infer_cmd_base(
                infer_cmd,
                root=effective_root,
                frame_s=frame_s,
                ranking=ranking,
                outbase=outbase_safe,
                img_type=img_type,
                idlabel=idlabel,
                show_mut=show_mut,
                summarize_forest=summarize_forest,
                tree_stats=tree_stats,
                params=p,
                positionmap=positionmap_path,
                positionmap2=positionmap_path2,
            )
            step = run_capture(infer_cmd, cwd=tmp)
            logs.append({**step, "step": "gctree_infer"})
            infer_ok = bool(step["ok"])
            gctree_nk_trees = collect_newicks(tmp, outbase_safe, top_n)

            if not infer_ok:
                logs.append(
                    {
                        "step": "fallback_outtree",
                        "ok": bool(fallback_trees),
                        "out": f"gctree infer failed; {len(fallback_trees)} DNAPARS outtree Newick(s) available (unranked, debug only).",
                    }
                )

            if infer_ok:
                result_quality = RESULT_GCTREE_RANKED
            elif fallback_trees:
                result_quality = RESULT_FALLBACK_DNAPARS
                used_fallback_trees = True
            else:
                result_quality = RESULT_FAILED

        # ----- trees & figures -----
        trees = gctree_nk_trees
        if not trees and fallback_trees:
            trees = fallback_trees
            used_fallback_trees = True

        if used_fallback_trees:
            warnings.append(
                {
                    "code": "UNRANKED_DNAPARS_FALLBACK",
                    "message": "Returned unranked DNAPARS Newick tree(s) for debugging only; this is not a GCtree-ranked result.",
                }
            )

        figures = collect_figures(tmp)

        ok_final = infer_ok
        err_msg: Optional[str] = None
        status_code = 200
        if not ok_final:
            status_code = 400
            last_fail = next(
                (L for L in reversed(logs) if not L.get("ok")), None
            )
            err_msg = (
                (last_fail.get("out") if last_fail else None)
                or "GCtree run did not complete successfully"
            )

        if infer_ok and apply_coloring:
            colored_url, cmeta, coloring_warn = render_colored_phylogeny_from_pickle(
                tmp=tmp,
                outbase=outbase_safe,
                color_mode=color_mode,
                logs=logs,
            )
            warnings.extend(coloring_warn)
            render_meta["coloring"] = cmeta
            if colored_url:
                figures.setdefault("phylogeny", [])
                figures["phylogeny"].insert(0, colored_url)
            elif cmeta.get("enabled"):
                warnings.append(
                    {
                        "code": "COLORING_FAILED",
                        "message": "Post-inference coloring failed; ranked GCtree outputs are unchanged.",
                    }
                )
        elif not apply_coloring:
            render_meta["coloring"] = {
                "enabled": False,
                "mode": "none",
                "feature": None,
                "palette": "viridis",
                "requested_scale": None,
                "effective_scale": None,
                "scale_fallback_reason": None,
                "vmin": None,
                "vmax": None,
                "colored_tree_rank": None,
                "missing_value_count": 0,
                "invalid_value_count": 0,
            }

        if infer_ok and apply_isotype:
            effective_isotype_idmap, idmap_source = select_effective_isotype_idmap(
                isotype_idmap,
                bridged_original_idmap,
                idmap_txt,
                generated_or_bundle_idmap_source,
            )

            isomap = isotype_map if (isotype_map and isotype_map.is_file()) else None

            if effective_isotype_idmap and isomap:
                logs.append(
                    {
                        "step": "isotype_idmap_selected",
                        "ok": True,
                        "out": (
                            f"Using {effective_isotype_idmap.name} for isotype "
                            f"(source={idmap_source})."
                        ),
                    }
                )
                tree_pickles = sorted(tmp.glob(f"{outbase_safe}.inference.*.p"))
                iso_m = run_isotype_step(
                    tmp,
                    logs,
                    effective_isotype_idmap,
                    isomap,
                    tree_pickles,
                )
                iso_m["idmap_source"] = idmap_source
                iso_m["effective_idmap_file"] = effective_isotype_idmap.name
                render_meta["isotype"] = iso_m
                if iso_m.get("applied"):
                    warnings.append(
                        {
                            "code": "ISOTYPE_NOT_SIMPLE_COLORING",
                            "message": "Isotype annotation is not simple tree coloring; it can change how GCtree renders intermediate node states.",
                        }
                    )
                else:
                    warnings.append(
                        {
                            "code": "ISOTYPE_FAILED",
                            "message": "isotype utility did not complete successfully; see logs.",
                        }
                    )
            else:
                render_meta["isotype"] = {
                    "applied": False,
                    "skipped": True,
                    "idmap_source": idmap_source,
                    "effective_idmap_file": (
                        effective_isotype_idmap.name
                        if effective_isotype_idmap is not None
                        else None
                    ),
                    "artifacts": [],
                }
                parts: List[str] = []
                if not isomap:
                    parts.append(
                        "apply_isotype requires isotype_mapfile in the ZIP manifest."
                    )
                if effective_isotype_idmap is None:
                    parts.append(
                        "No isotype idmap available: add idmapfile_isotype to the ZIP, "
                        "or ensure idmap.original.tsv/idmap.txt exists from deduplicate (FASTA) "
                        "or idmapfile in a DNAPARS bundle."
                    )
                warnings.append(
                    {
                        "code": "ISOTYPE_MISSING_FILES",
                        "message": " ".join(parts),
                    }
                )
        elif apply_isotype:
            render_meta["isotype"] = {
                "applied": False,
                "skipped": True,
                "idmap_source": "missing",
                "effective_idmap_file": None,
                "artifacts": [],
            }
            warnings.append(
                {
                    "code": "ISOTYPE_SKIPPED_INFER_FAILED",
                    "message": "apply_isotype was not run because GCtree inference did not succeed.",
                }
            )

        stats: Dict[str, Any] = {
            "input_scenario": input_scenario,
            "result_quality": result_quality,
            "n_trees_found": len(trees),
            "infer_succeeded": infer_ok,
            "used_unranked_dnapars_fallback": used_fallback_trees,
            "original_root": original_root,
            "effective_root": effective_root,
            "fasta_ids_remapped": fasta_remapped_count,
        }
        if fasta_idmap_artifact:
            stats["fasta_idmap"] = fasta_idmap_artifact
        if response_idmap_path != idmap_txt:
            stats["response_idmap"] = response_idmap_path.name

        resp = _base_payload(
            ok=ok_final,
            trees=trees,
            figures=figures,
            logs=logs,
            tmp=tmp,
            outbase=outbase_safe,
            abund_csv=abund_csv,
            idmap_txt=idmap_txt,
            warnings=warnings,
            render_meta=render_meta,
            stats=stats,
            error=err_msg,
            status_code=status_code,
            response_idmap_path=response_idmap_path,
        )
        return resp

    finally:
        keep = os.getenv("KEEP_TMP") == "1"
        if keep:
            print(f"[gctree-bridge] keeping temp dir at: {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)


if not STRICT_CONTRACT_ROUTES:

    @app.post("/run")  # type: ignore
    async def _run_alias(request: Request):
        return await run_handler(request)


# ---------- Async job execution (/jobs contract) ----------
from job_manager import JobManager  # noqa: E402

job_manager = JobManager(METHOD_ID)


def run_job_sync(file_path, params) -> Tuple[int, Any]:
    """Invoke the existing /run handler synchronously in this (child) process.

    Reuses run_handler unchanged by constructing a JSON request, so the
    scientific pipeline is not duplicated or modified.
    """
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
