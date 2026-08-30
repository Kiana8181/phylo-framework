# services/clonaltree/validators.py
#
# In-service pre-flight validation for ClonalTree input, modeled on the
# structured hard-fail/warning separation used by Dowser's validators.R.
#
# Design constraints (see plan):
#   * Read-only inspection of the staged AIRR table. Never mutates input.
#   * Nothing here touches the base-codes/ submodule.
#   * Hard-fail ONLY on genuinely fatal issues (unreadable/empty file, missing
#     truly-required columns, empty/duplicate sequence_id). Everything the
#     downstream submodule currently tolerates (rows it silently drops via
#     dropna, non-uniform alignment lengths that MUSCLE re-aligns, etc.) is a
#     WARNING so currently-working inputs keep running.
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Provably-required for the pipeline to produce any output. Missing any of
# these means the run cannot succeed, so we reject up front with a clear
# message instead of failing opaquely deep in the submodule.
# Mirrors apps/api/preprocess/column_requirements.py::CLONALTREE_BASE_REQUIRED_KEYS
# (the subset the pipeline genuinely depends on).
REQUIRED_COLUMNS: Tuple[str, ...] = (
    "sequence_id",
    "sequence_alignment",
    "cdr3_aa",
    "v_call",
    "j_call",
)

# Part of the AIRR base set but tolerated if absent (format step intersects
# available columns). Missing these only reduces fidelity -> warn, don't fail.
RECOMMENDED_BASE_COLUMNS: Tuple[str, ...] = (
    "productive",
    "d_call",
    "junction_aa",
)

# Used only when refinement runs (use_refinement, default True). Absence
# degrades/skips refinement inside the submodule rather than aborting -> warn.
REFINEMENT_COLUMNS: Tuple[str, ...] = (
    "j_sequence_alignment",
    "v_sequence_alignment",
    "j_sequence_alignment_aa",
    "v_sequence_alignment_aa",
)

# Columns whose empty values cause rows to be dropped downstream
# (base-codes/src/cluster/initial_clustering.py dropna on these). We surface a
# count so the user knows rows will silently disappear, but we do not stop.
INCOMPLETE_CHECK_COLUMNS: Tuple[str, ...] = ("cdr3_aa", "v_call", "j_call")

# Known AIRR / ClonalTree field names for a light "looks like AIRR" signal.
# Only used to warn about wholly-unrecognized headers; never used to reject.
_KNOWN_AIRR_COLUMNS: frozenset[str] = frozenset(
    {
        *REQUIRED_COLUMNS,
        *RECOMMENDED_BASE_COLUMNS,
        *REFINEMENT_COLUMNS,
        "sequence",
        "junction",
        "junction_length",
        "np1",
        "np2",
        "clone_id",
        "cell_id",
        "locus",
        "rev_comp",
        "vj_in_frame",
        "stop_codon",
        "complete_vdj",
        "germline_alignment",
        "germline_alignment_d_mask",
        "v_germline_alignment",
        "d_germline_alignment",
        "j_germline_alignment",
        "v_identity",
        "d_identity",
        "j_identity",
        "v_support",
        "d_support",
        "j_support",
        "cdr1",
        "cdr2",
        "cdr3",
        "fwr1",
        "fwr2",
        "fwr3",
        "fwr4",
        "cdr1_aa",
        "cdr2_aa",
        "cdr3_aa",
        "fwr1_aa",
        "fwr2_aa",
        "fwr3_aa",
        "fwr4_aa",
        "v_sequence_start",
        "v_sequence_end",
        "d_sequence_start",
        "d_sequence_end",
        "j_sequence_start",
        "j_sequence_end",
        "cdr1_start",
        "cdr1_end",
        "cdr2_start",
        "cdr2_end",
        "cdr3_start",
        "cdr3_end",
        "v_region_start",
        "v_region_end",
        "j_region_start",
        "j_region_end",
        "duplicate_count",
        "consensus_count",
    }
)

# Cap how many example values we echo back in messages/details.
_MAX_EXAMPLES = 5
# Cap how many unrecognized headers we list in the warning.
_MAX_UNKNOWN_HEADERS = 8


@dataclass
class ValidationResult:
    """Outcome of a pre-flight validation pass.

    ok=False means a fatal problem: the caller should reject the run. warnings
    are always advisory and never block the run (ok may still be True).
    """

    ok: bool = True
    error: Optional[str] = None
    error_details: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    def _fail(self, message: str, **details: Any) -> "ValidationResult":
        self.ok = False
        self.error = message
        self.error_details = dict(details)
        return self


def _truthy(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y", "on"}
    return default


def _sniff_delimiter(first_line: str) -> str:
    """Pick tab vs comma from the header line.

    ClonalTree input is AIRR TSV, but a direct upload could be comma-separated;
    the framework also converts CSV->TSV upstream. Tab wins when present.
    """
    if "\t" in first_line:
        return "\t"
    if "," in first_line:
        return ","
    return "\t"


def _normalize(name: str) -> str:
    return name.strip().lower()


def _read_table(
    input_path: Path,
) -> Tuple[Optional[List[str]], List[List[str]], Optional[str]]:
    """Read the table.

    Returns (header, rows, error_message). header/rows are None/empty when an
    error_message is returned. Uses utf-8-sig to transparently strip a leading
    BOM so a '\\ufeffsequence_id' header still matches.
    """
    try:
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.readline()
            if not sample.strip():
                return None, [], "Input file is empty or has no header row."
            delimiter = _sniff_delimiter(sample)
            handle.seek(0)
            reader = csv.reader(handle, delimiter=delimiter)
            rows = list(reader)
    except FileNotFoundError:
        return None, [], "Input file could not be found on the server."
    except OSError as exc:
        return None, [], f"Input file could not be read: {exc}"
    except csv.Error as exc:
        return None, [], f"Input file could not be parsed as a table: {exc}"

    if not rows:
        return None, [], "Input file is empty or has no header row."

    header = [_normalize(col) for col in rows[0]]
    body = rows[1:]
    return header, body, None


def _cell(row: List[str], index: int) -> str:
    if index < 0 or index >= len(row):
        return ""
    value = row[index]
    return value.strip() if isinstance(value, str) else str(value).strip()


def validate_clonaltree_input(input_path: Path, params: Dict[str, Any]) -> ValidationResult:
    """Validate a ClonalTree AIRR input file before the pipeline runs.

    Returns a ValidationResult. On a fatal problem, ok is False and error holds
    a user-facing message. Non-fatal issues are collected in warnings and never
    block the run.
    """
    result = ValidationResult()

    header, body, read_error = _read_table(input_path)
    if read_error is not None:
        return result._fail(read_error, code="unreadable_input")
    assert header is not None

    # Fatal: required columns must be present.
    header_set = set(header)
    missing_required = [c for c in REQUIRED_COLUMNS if c not in header_set]
    if missing_required:
        return result._fail(
            "Input is missing required column(s) for ClonalTree: "
            + ", ".join(missing_required)
            + ". Provide an AIRR rearrangement table with these fields.",
            code="missing_required_columns",
            missing_columns=missing_required,
            required_columns=list(REQUIRED_COLUMNS),
            available_columns=header,
        )

    col_index = {name: idx for idx, name in enumerate(header)}
    id_idx = col_index["sequence_id"]
    align_idx = col_index["sequence_alignment"]

    # Single pass over the body: sequence_id empties/duplicates,
    # incomplete-row counts, and alignment-length spread.
    n_rows = 0
    empty_id_rows: List[int] = []
    seen_ids: Dict[str, int] = {}
    duplicate_examples: List[str] = []
    duplicate_ids: set[str] = set()
    incomplete_counts: Dict[str, int] = {c: 0 for c in INCOMPLETE_CHECK_COLUMNS if c in col_index}
    alignment_lengths: set[int] = set()

    for offset, row in enumerate(body):
        # Skip fully-blank padding rows (Excel-style trailing lines).
        if not any(isinstance(c, str) and c.strip() for c in row):
            continue
        n_rows += 1
        row_number = offset + 2  # 1-based, +1 for header

        seq_id = _cell(row, id_idx)
        if not seq_id:
            if len(empty_id_rows) < _MAX_EXAMPLES:
                empty_id_rows.append(row_number)
        else:
            if seq_id in seen_ids:
                if seq_id not in duplicate_ids:
                    duplicate_ids.add(seq_id)
                    if len(duplicate_examples) < _MAX_EXAMPLES:
                        duplicate_examples.append(seq_id)
            else:
                seen_ids[seq_id] = row_number

        for col in incomplete_counts:
            if not _cell(row, col_index[col]):
                incomplete_counts[col] += 1

        align_value = _cell(row, align_idx)
        if align_value:
            alignment_lengths.add(len(align_value))

    # Fatal: no data rows at all.
    if n_rows == 0:
        return result._fail(
            "Input file has a header but no data rows.",
            code="no_data_rows",
        )

    # Fatal: empty sequence_id values (cannot map tree tips).
    if empty_id_rows:
        return result._fail(
            f"Found empty sequence_id value(s); every row needs a unique identifier. "
            f"Example row(s): {', '.join(str(r) for r in empty_id_rows)}.",
            code="empty_sequence_id",
            example_rows=empty_id_rows,
        )

    # Fatal: duplicate sequence_id values (breaks stable tree tip mapping).
    if duplicate_ids:
        return result._fail(
            f"Found {len(duplicate_ids)} duplicated sequence_id value(s); identifiers must be "
            f"unique. Example(s): {', '.join(duplicate_examples)}.",
            code="duplicate_sequence_id",
            duplicate_count=len(duplicate_ids),
            examples=duplicate_examples,
        )

    # Fatal only when the input alignment is consumed as given. Without
    # `use_input_alignment` MUSCLE re-aligns, so unequal lengths are legitimate
    # and stay a warning below.
    if len(alignment_lengths) > 1 and _truthy(
        params.get("use_input_alignment"), default=False
    ):
        return result._fail(
            "use_input_alignment is enabled, so sequence_alignment values are used as "
            f"given, but they are not all the same length (found {len(alignment_lengths)} "
            f"distinct lengths: {', '.join(str(n) for n in sorted(alignment_lengths))}). "
            "Either supply an aligned input of uniform length or disable "
            "use_input_alignment so MUSCLE re-aligns the sequences.",
            code="alignment_length_mismatch",
            distinct_lengths=sorted(alignment_lengths),
        )

    # ---- Warnings (never block the run) ----

    missing_recommended = [c for c in RECOMMENDED_BASE_COLUMNS if c not in header_set]
    if missing_recommended:
        result.warnings.append(
            "Input is missing recommended AIRR column(s): "
            + ", ".join(missing_recommended)
            + ". The run will proceed but results may be less complete."
        )

    if _truthy(params.get("use_refinement"), default=True):
        missing_refinement = [c for c in REFINEMENT_COLUMNS if c not in header_set]
        if missing_refinement:
            result.warnings.append(
                "Refinement is enabled but the input lacks column(s): "
                + ", ".join(missing_refinement)
                + ". Refinement may be skipped or degraded for affected sequences."
            )

    for col, count in incomplete_counts.items():
        if count:
            result.warnings.append(
                f"{count} row(s) have an empty '{col}' value and will be dropped "
                f"before clustering."
            )

    # Reached only when use_input_alignment is off; with it on, the check above
    # has already failed the run.
    if len(alignment_lengths) > 1:
        result.warnings.append(
            "sequence_alignment values are not all the same length "
            f"(found {len(alignment_lengths)} distinct lengths); ClonalTree will "
            "re-align sequences with MUSCLE."
        )

    unknown_headers = [c for c in header if c and c not in _KNOWN_AIRR_COLUMNS]
    if unknown_headers:
        shown = unknown_headers[:_MAX_UNKNOWN_HEADERS]
        suffix = "" if len(unknown_headers) <= _MAX_UNKNOWN_HEADERS else ", ..."
        result.warnings.append(
            "Input contains non-standard/unrecognized column(s): "
            + ", ".join(shown)
            + suffix
            + ". These are ignored by ClonalTree."
        )

    return result
