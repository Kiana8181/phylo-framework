from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from apps.api.preprocess.column_requirements import (
    CLONALTREE_ALIGNMENT_REQUIRED_KEYS,
    CLONALTREE_BASE_REQUIRED_KEYS,
    CLONALTREE_PREALIGNED_GERMLINE_REQUIRED_KEYS,
    CLONALTREE_REFINEMENT_REQUIRED_KEYS,
    DOWSER_HL_REQUIRED_KEYS,
    DOWSER_REGION_REQUIRED_KEYS,
    DOWSER_REQUIRED_KEYS,
    REQUIRED_KEYS_BY_METHOD,
)
from apps.api.preprocess.converters import (
    ConversionError,
    convert_csv_to_tsv,
    convert_table_to_aligned_fasta,
    convert_tsv_to_csv,
    insert_root_row,
    normalize_table_delimiter,
    rename_table_columns,
    _table_delimiter,
)
from apps.api.preprocess.validate_input import (
    InputValidationError,
    validate_airr_table,
)
from apps.api.preprocess.method_capabilities import (
    describe_safe_paths,
    extension_from_path,
    is_native_accept,
    native_accepts,
    normalize_extension,
    safe_conversion_chain,
)

VALID_METHODS: set[str] = {"dowser", "brepphylo", "clonaltree", "gctree"}
TABULAR_EXTENSIONS = {"csv", "tsv"}
MAPPING_METHODS = {"dowser", "clonaltree", "gctree"}
CANONICAL_SEQUENCE_ID_KEY = "sequence_id"
GCTREE_ALIGNED_COLUMN_DEFAULT = "sequence_alignment"
GCTREE_ALIGNED_COLUMN_KEYS = (
    "aligned_seq_column",
    "aligned_sequence_column",
    "sequence_alignment_column",
    "alignment_column",
)
GCTREE_ID_COLUMN_KEYS = ("id_column", "sequence_id_column", "fasta_id_column")
GCTREE_TABLE_ADAPTER_SCENARIO = "airr_or_changeo_table_adapter"
GCTREE_ALIGNED_COLUMN_SYNONYMS = (
    "sequence_alignment",
    "aligned_sequence",
    "aligned_seq",
    "alignment",
)

INVALID_FILE_CONVERTER_CODES = {"PARSE_ERROR", "EMPTY_TABLE", "ROW_WIDTH_MISMATCH", "READ_ERROR"}
GCTREE_ALIGNMENT_CONVERTER_CODES = {
    "INVALID_ALIGNED_COLUMN",
    "COLUMN_NOT_FOUND",
    "AMBIGUOUS_COLUMN",
    "MISSING_ALIGNED_SEQUENCE",
    "ALIGNMENT_LENGTH_MISMATCH",
}
# Identifier defects on the GCtree table->FASTA path. Kept out of the set above
# because folding them into the generic "requires an aligned sequence column"
# message named the wrong cause: a duplicated ID has nothing to do with the
# alignment. FASTA headers must be unique, so these stay fatal here.
GCTREE_IDENTIFIER_CONVERTER_CODES = {"EMPTY_ID", "DUPLICATE_IDS"}


@dataclass
class PreprocessError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


@dataclass
class PreparedInput:
    final_path: Path
    final_ext: str
    applied_steps: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    stats: dict[str, Any]
    log_entries: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["final_path"] = str(self.final_path)
        return payload


# Prefix that distinguishes orchestrator preprocessing entries from the method
# services' own `method.*` entries and the worker's `api.worker.*` ones in the
# run's `logs` array. The shape is RunLogEntry ({step, ok, cmd, out}) so the
# client renders them without special-casing.
PREPROCESS_LOG_PREFIX = "preprocess"


def _preprocess_log(step: str, out: str, ok: bool = True) -> dict[str, Any]:
    """Build one RunLogEntry-shaped record for an executed preprocessing step."""
    return {"step": f"{PREPROCESS_LOG_PREFIX}.{step}", "ok": ok, "out": out}


def _summary_log(
    *,
    method: str,
    applied_steps: list[dict[str, Any]],
    input_ext: str,
    final_ext: str,
    note: str,
) -> dict[str, Any]:
    """Terminal entry naming every step that ran.

    Steps that were skipped emit no entry of their own, so this summary is what
    makes their absence unambiguous rather than merely silent.
    """
    names = [str(entry.get("step")) for entry in applied_steps]
    return _preprocess_log(
        "summary",
        "method={method}; input=.{input_ext} -> prepared=.{final_ext}; "
        "steps applied={count} [{names}]; {note}".format(
            method=method,
            input_ext=input_ext,
            final_ext=final_ext,
            count=len(names),
            names=", ".join(names) if names else "none",
            note=note,
        ),
    )


def _fmt_delimiter(char: Any) -> str:
    """Render a delimiter as a readable token rather than a raw control char."""
    return {"\t": "tab", ",": "comma", ";": "semicolon", "|": "pipe"}.get(
        char, repr(char)
    )


def _fmt_step_warnings(messages: Any) -> str:
    """Render a step's own warnings for its log entry, or '' when it raised none.

    The warnings themselves stay on `PreparedInput.warnings` — this only makes
    them traceable alongside the step that raised them.
    """
    texts = [str(m) for m in (messages or []) if str(m).strip()]
    if not texts:
        return ""
    return "; warnings={n} [{texts}]".format(n=len(texts), texts="; ".join(texts))


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}
    return False


def _do_mapping(params: dict[str, Any]) -> bool:
    return _truthy(params.get("doMapping"))


def _uses_clonaltree_refinement(params: dict[str, Any]) -> bool:
    if "use_refinement" not in params:
        return True
    return _truthy(params.get("use_refinement"))


def _uses_clonaltree_input_alignment(params: dict[str, Any]) -> bool:
    return _truthy(params.get("use_input_alignment"))


def active_required_keys(method_id: str, params: dict[str, Any]) -> list[str]:
    method = method_id.lower().strip()
    if method == "clonaltree":
        required = list(CLONALTREE_BASE_REQUIRED_KEYS)
        if _uses_clonaltree_refinement(params):
            required.extend(CLONALTREE_REFINEMENT_REQUIRED_KEYS)
        if _uses_clonaltree_input_alignment(params):
            required.extend(CLONALTREE_PREALIGNED_GERMLINE_REQUIRED_KEYS)
        else:
            required.extend(CLONALTREE_ALIGNMENT_REQUIRED_KEYS)
        return required
    if method == "dowser":
        required = list(DOWSER_REQUIRED_KEYS)
        chain_mode = str(params.get("chain_mode") or "H").strip().upper()
        if chain_mode == "HL":
            required.extend(DOWSER_HL_REQUIRED_KEYS)
        if _truthy(params.get("use_regions")):
            required.extend(DOWSER_REGION_REQUIRED_KEYS)
        return required
    return list(REQUIRED_KEYS_BY_METHOD.get(method, []))


def _get_column_map(params: dict[str, Any]) -> dict[str, str]:
    raw = params.get("column_map")
    if not isinstance(raw, dict):
        return {}

    out: dict[str, str] = {}
    for key, value in raw.items():
        if not isinstance(key, str) or not isinstance(value, str):
            continue
        clean_key = key.strip()
        clean_value = value.strip()
        if clean_key and clean_value:
            out[clean_key] = clean_value
    return out


def should_apply_column_mapping(method_id: str, input_ext: str, params: dict[str, Any]) -> bool:
    method = method_id.lower().strip()
    normalized_ext = normalize_extension(input_ext)
    if method not in MAPPING_METHODS:
        return False
    if normalized_ext not in TABULAR_EXTENSIONS:
        return False
    return _do_mapping(params)


def _string_param(params: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _gctree_aligned_seq_column(params: dict[str, Any]) -> str:
    explicit = _string_param(params, GCTREE_ALIGNED_COLUMN_KEYS)
    if explicit:
        return explicit
    for key in GCTREE_ALIGNED_COLUMN_SYNONYMS:
        value = params.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return GCTREE_ALIGNED_COLUMN_DEFAULT


def _gctree_id_column(params: dict[str, Any]) -> str | None:
    return _string_param(params, GCTREE_ID_COLUMN_KEYS)


def _gctree_root_row_to_add(
    method: str, params: dict[str, Any]
) -> tuple[str, str] | None:
    """The (id, aligned sequence) of a germline row the user asked us to add.

    None when the table already carries its germline row, which is both the
    default and what an older run's params imply — they predate the question, so
    a missing answer must keep meaning "the row is already there".
    """
    if method != "gctree":
        return None
    scenario = str(params.get("input_scenario") or "").strip()
    if scenario != GCTREE_TABLE_ADAPTER_SCENARIO:
        return None
    answer = str(params.get("germline_row_present") or "yes").strip().lower()
    if answer != "no":
        return None

    root_id = str(params.get("root_sequence_id") or "").strip()
    root_sequence = str(params.get("root_sequence_alignment") or "").strip()
    missing = [
        name
        for name, value in (
            ("root_sequence_id", root_id),
            ("root_sequence_alignment", root_sequence),
        )
        if not value
    ]
    if missing:
        raise PreprocessError(
            code="MISSING_ROOT_SEQUENCE",
            message=(
                "You indicated the input table has no germline row, so GCtree needs "
                "both an identifier and an aligned sequence for the row to add."
            ),
            details={
                "method_id": method,
                "step": "insert_root_row",
                "missing_params": missing,
                "next_actions": [
                    "Fill in the root sequence ID and the aligned germline sequence.",
                    "Or answer that the table already includes the germline row and name it instead.",
                ],
            },
        )
    return root_id, root_sequence


def _validation_columns(method: str, params: dict[str, Any]) -> dict[str, str]:
    """Resolve the (id, sequence) column names as they appear in the *uploaded*
    file, so structural validation can run before any renaming.

    This is name resolution, not policy: each method simply calls these columns
    something different. GCtree names them through its aligned-column params,
    BrepPhylo through flat `*_column` params, and the column-mapping methods
    through `column_map` (canonical key -> source header).

    Whether a given table property is *acceptable* is not decided here — see
    the module docstring of `validate_input.py`.
    """
    if method == "gctree":
        id_column = _gctree_id_column(params) or "sequence_id"
        sequence_column = _gctree_aligned_seq_column(params)
    elif method == "brepphylo":
        id_column = (
            _string_param(params, ("tip_id_column", "label_column")) or "sequence_id"
        )
        sequence_column = (
            _string_param(params, ("sequence_column",)) or "sequence_alignment"
        )
    else:
        id_column = "sequence_id"
        sequence_column = "sequence_alignment"

    column_map = _get_column_map(params)
    if column_map and should_apply_column_mapping(method, "tsv", params):
        id_column = column_map.get(id_column, id_column)
        sequence_column = column_map.get(sequence_column, sequence_column)

    return {"id_column": id_column, "sequence_column": sequence_column}


def _table_stats(path: Path, ext: str) -> dict[str, int]:
    hint: Literal["csv", "tsv"] | None = (
        "csv" if ext == "csv" else "tsv" if ext == "tsv" else None
    )
    try:
        delimiter = _table_delimiter(path, delimiter=hint)
    except ConversionError:
        delimiter = "," if ext == "csv" else "\t"
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        rows = list(reader)
    if not rows:
        return {"rows": 0, "cols": 0}
    return {"rows": len(rows) - 1, "cols": len(rows[0])}


def _unsupported_input_error(method_id: str, input_ext: str) -> PreprocessError:
    return PreprocessError(
        code="UNSUPPORTED_INPUT",
        message=f"{method_id} does not safely accept '.{input_ext}' input.",
        details={
            "method_id": method_id,
            "input_ext": input_ext,
            "allowed": sorted(native_accepts(method_id)),  # type: ignore[arg-type]
            "safe_paths": describe_safe_paths(method_id),  # type: ignore[arg-type]
            "next_actions": [
                "Upload a natively accepted format for this method.",
                "If using GCtree tabular input, provide an aligned sequence column or upload aligned FASTA.",
            ],
        },
    )


def _join_readable(items: list[str], *, limit: int = 12) -> str:
    if not items:
        return ""
    if len(items) <= limit:
        return ", ".join(items)
    remainder = len(items) - limit
    return f"{', '.join(items[:limit])}, and {remainder} more"


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _canonical_keys_for_source(column_map: dict[str, str], source_column: str) -> list[str]:
    return [canonical for canonical, source in column_map.items() if source == source_column]


def _column_mapping_step_message(
    exc: ConversionError,
    *,
    column_map: dict[str, str],
    step: str,
) -> str:
    details = exc.details or {}

    if exc.code == "COLUMN_NOT_FOUND":
        requested = details.get("requested_column")
        if isinstance(requested, str) and requested.strip():
            canonical_keys = _canonical_keys_for_source(column_map, requested.strip())
            if canonical_keys:
                return (
                    f"Column mapping at step '{step}' could not find source column "
                    f"'{requested}' (mapped from {_join_readable(canonical_keys)})."
                )
            return (
                f"Column mapping at step '{step}' could not find column "
                f"'{requested}' in the input table."
            )

    if exc.code == "AMBIGUOUS_COLUMN":
        duplicated = _string_list(details.get("duplicated_headers"))
        if duplicated:
            return (
                f"Column mapping at step '{step}' would create duplicate headers: "
                f"{_join_readable(duplicated)}."
            )

        source_column = details.get("source_column")
        canonical_keys = _string_list(details.get("canonical_keys"))
        if isinstance(source_column, str) and source_column.strip() and canonical_keys:
            return (
                f"Column mapping at step '{step}' maps multiple fields to the same source column "
                f"'{source_column}': {_join_readable(canonical_keys)}."
            )

        requested = details.get("requested_column")
        matches = _string_list(details.get("matches"))
        if isinstance(requested, str) and requested.strip() and matches:
            return (
                f"Column mapping at step '{step}' is ambiguous for '{requested}': "
                f"matches multiple headers ({_join_readable(matches)})."
            )

    if exc.code in INVALID_FILE_CONVERTER_CODES:
        return f"Column mapping at step '{step}' failed while reading the input table: {exc.message}"

    return f"Column mapping at step '{step}' failed: {exc.message}"


def _missing_mapping_message(missing: list[str], *, step: str) -> str:
    if missing:
        return (
            f"Input is missing required columns after column mapping at step '{step}': "
            f"{_join_readable(missing)}."
        )
    return f"Input is missing one or more required columns after column mapping at step '{step}'."


def _conversion_error(
    method_id: str,
    input_ext: str,
    message: str,
    converter_error: ConversionError | None = None,
    *,
    code: str = "CONVERSION_FAILED",
    step: str | None = None,
    extra_details: dict[str, Any] | None = None,
) -> PreprocessError:
    details: dict[str, Any] = {
        "method_id": method_id,
        "input_ext": input_ext,
        "step": step,
        "next_actions": [
            "Verify the input file format and header names.",
            "Upload a natively accepted file for this method if conversion is not possible.",
        ],
    }
    if converter_error is not None:
        details["converter_error"] = converter_error.to_dict()
    if extra_details:
        details.update(extra_details)
    return PreprocessError(code=code, message=message, details=details)


def _missing_mapping_error(
    *,
    method_id: str,
    input_ext: str,
    required_keys: list[str],
    column_map: dict[str, str],
    converter_error: ConversionError,
    step: str,
) -> PreprocessError:
    missing = _string_list(converter_error.details.get("missing_required_keys"))
    input_columns = _string_list(converter_error.details.get("available_columns"))
    resolved_map = converter_error.details.get("resolved_map")
    resolved = resolved_map if isinstance(resolved_map, dict) else {}
    example_mapping = {key: f"<column for {key}>" for key in required_keys}
    return PreprocessError(
        code="MISSING_COLUMN_MAPPING",
        message=_missing_mapping_message(missing, step=step),
        details={
            "method_id": method_id,
            "input_ext": input_ext,
            "step": step,
            "required_keys": required_keys,
            "missing_keys": missing,
            "input_columns": input_columns,
            "resolved_map": resolved,
            "column_map": column_map,
            "example_column_map": example_mapping,
            "converter_error": converter_error.to_dict(),
            "next_actions": [
                "Map the missing source columns to their required canonical names.",
                "Or rename your input headers to match the required canonical names and retry.",
            ],
        },
    )


def prepare_input_for_method(
    method_id: Literal["dowser", "brepphylo", "clonaltree", "gctree"],
    uploaded_path: Path,
    *,
    params: dict[str, Any],
    work_dir: Path,
) -> PreparedInput:
    method = method_id.lower().strip()
    if method not in VALID_METHODS:
        raise PreprocessError(
            code="UNSUPPORTED_INPUT",
            message=f"Unsupported method '{method_id}'.",
            details={"method_id": method_id, "next_actions": ["Use one of: dowser, brepphylo, clonaltree, gctree."]},
        )

    if not uploaded_path.exists() or not uploaded_path.is_file():
        raise PreprocessError(
            code="INVALID_FILE",
            message="Uploaded file is missing or unreadable on the server.",
            details={
                "method_id": method,
                "path": str(uploaded_path),
                "next_actions": ["Re-upload the file and retry."],
            },
        )

    input_ext = extension_from_path(uploaded_path)
    if not input_ext:
        raise PreprocessError(
            code="INVALID_FILE",
            message="Input file has no extension; cannot determine format safely.",
            details={
                "method_id": method,
                "path": str(uploaded_path),
                "next_actions": ["Rename the file with a supported extension and retry."],
            },
        )

    work_dir.mkdir(parents=True, exist_ok=True)
    normalized_ext = normalize_extension(input_ext)
    stats: dict[str, Any] = {"method_id": method, "input_ext": normalized_ext}
    warnings: list[dict[str, Any]] = []
    applied_steps: list[dict[str, Any]] = []
    log_entries: list[dict[str, Any]] = []
    current_path = uploaded_path
    current_ext = normalized_ext
    step_offset = 0
    mapping_applied = False

    # Always sanitize tabular uploads before any other step: rewrite with the
    # canonical delimiter for the extension, strip a leading UTF-8 BOM, and
    # drop fully-blank padding rows that Excel often appends. Without this,
    # semicolon-CSV exports reach Dowser as a single concatenated column,
    # BOM-prefixed headers silently miss required-column checks, and
    # empty `;;;;;;...` rows trip validators downstream.
    if current_ext in TABULAR_EXTENSIONS:
        # An empty upload is checked before delimiter normalization, which would
        # otherwise reject it first with a message about the normalization step
        # rather than about the file.
        try:
            upload_is_empty = current_path.stat().st_size == 0
        except OSError:
            upload_is_empty = False
        if upload_is_empty:
            raise PreprocessError(
                code="INPUT_EMPTY_FILE",
                message=(
                    "The input file is empty (0 bytes). Upload a table with a "
                    "header row and at least one data row."
                ),
                details={
                    "method_id": method,
                    "step": "validate_input_table",
                    "path": current_path.name,
                    "next_actions": ["Correct the input table and re-upload it."],
                },
            )

        delimiter_hint: Literal["csv", "tsv"] = (
            "csv" if current_ext == "csv" else "tsv"
        )
        step_offset += 1
        step_name = "normalize_table_delimiter"
        output_path = work_dir / f"{step_offset:02d}_{step_name}.{current_ext}"
        try:
            norm_stats = normalize_table_delimiter(
                current_path,
                output_path,
                delimiter=delimiter_hint,
            )
        except ConversionError as exc:
            mapped_code = (
                "INVALID_FILE"
                if exc.code in INVALID_FILE_CONVERTER_CODES
                else "CONVERSION_FAILED"
            )
            raise _conversion_error(
                method_id=method,
                input_ext=current_ext,
                message=(
                    f"Failed to normalize input table at step "
                    f"'{step_name}': {exc.message}"
                ),
                converter_error=exc,
                code=mapped_code,
                step=step_name,
            ) from exc
        stats[f"step_{step_offset}_table"] = {
            "rows": norm_stats.get("rows", 0),
            "cols": norm_stats.get("cols", 0),
            "input_delimiter": norm_stats.get("input_delimiter"),
            "output_delimiter": norm_stats.get("output_delimiter"),
            "blank_rows_dropped": norm_stats.get("blank_rows_dropped", 0),
            "bom_stripped": bool(norm_stats.get("bom_stripped")),
        }
        blank_dropped = int(norm_stats.get("blank_rows_dropped") or 0)
        in_delim = _fmt_delimiter(norm_stats.get("input_delimiter"))
        out_delim = _fmt_delimiter(norm_stats.get("output_delimiter"))
        log_entries.append(
            _preprocess_log(
                step_name,
                "file={name} delimiter={in_d}->{out_d}{unchanged}; "
                "rows={rows} columns={cols}; blank rows dropped={blank}; "
                "byte-order mark stripped={bom}".format(
                    name=current_path.name,
                    in_d=in_delim,
                    out_d=out_delim,
                    unchanged=" (unchanged)" if in_delim == out_delim else "",
                    rows=norm_stats.get("rows", 0),
                    cols=norm_stats.get("cols", 0),
                    blank=blank_dropped,
                    bom="yes" if norm_stats.get("bom_stripped") else "no",
                ),
            )
        )
        if blank_dropped:
            warnings.append(
                {
                    "code": "BLANK_ROWS_DROPPED",
                    "message": (
                        f"Dropped {blank_dropped} fully-blank padding row(s) "
                        "from the input table during normalization."
                    ),
                }
            )
        applied_steps.append(
            {
                "step": step_name,
                "from": current_ext,
                "to": current_ext,
                "input_path": str(current_path),
                "output_path": str(output_path),
            }
        )
        current_path = output_path

        # Add the germline row when the user told us their table lacks one. This
        # runs before validation so the synthesized row is checked for stray
        # characters alongside every other row, and before `rename_table_columns`
        # so the row is written under the user's own headers — `_validation_columns`
        # already resolves the column-mapped names, so nothing here has to know
        # about mapping.
        root_row = _gctree_root_row_to_add(method, params)
        if root_row is not None:
            root_id, root_sequence = root_row
            columns = _validation_columns(method, params)
            step_offset += 1
            step_name = "insert_root_row"
            output_path = work_dir / f"{step_offset:02d}_{step_name}.{current_ext}"
            try:
                root_stats = insert_root_row(
                    current_path,
                    output_path,
                    delimiter="csv" if current_ext == "csv" else "tsv",
                    id_column=columns["id_column"],
                    sequence_column=columns["sequence_column"],
                    root_id=root_id,
                    root_sequence=root_sequence,
                )
            except ConversionError as exc:
                if exc.code == "ROOT_SEQUENCE_LENGTH_MISMATCH":
                    next_actions = [
                        "Check the germline sequence you pasted — gap characters count towards its length.",
                        "Or answer that the table already includes the germline row and name it instead.",
                    ]
                elif exc.code == "ROOT_ID_ALREADY_PRESENT":
                    next_actions = [
                        "Choose an identifier that no row in the table uses.",
                        "Or answer that the table already includes the germline row and name that row instead.",
                    ]
                else:
                    next_actions = [
                        "Verify the input table has the identifier and aligned sequence columns.",
                        "If you enabled column mapping, check both mapped columns exist in the table.",
                    ]
                mapped_code = (
                    "INVALID_FILE"
                    if exc.code in INVALID_FILE_CONVERTER_CODES
                    else exc.code
                )
                raise _conversion_error(
                    method_id=method,
                    input_ext=current_ext,
                    message=exc.message,
                    converter_error=exc,
                    code=mapped_code,
                    step=step_name,
                    extra_details={"next_actions": next_actions},
                ) from exc

            stats[f"step_{step_offset}_root_row"] = {
                "rows": root_stats.get("rows", 0),
                "cols": root_stats.get("cols", 0),
                "root_id": root_stats.get("root_id"),
                "id_column": root_stats.get("id_column"),
                "sequence_column": root_stats.get("sequence_column"),
                "alignment_length": root_stats.get("alignment_length"),
            }
            log_entries.append(
                _preprocess_log(
                    step_name,
                    "file={name}; added germline row id='{root}' into column "
                    "'{idc}' with {length} aligned characters in column '{seqc}'; "
                    "rows={rows} columns={cols}".format(
                        name=current_path.name,
                        root=root_stats.get("root_id"),
                        idc=root_stats.get("id_column"),
                        length=root_stats.get("alignment_length"),
                        seqc=root_stats.get("sequence_column"),
                        rows=root_stats.get("rows", 0),
                        cols=root_stats.get("cols", 0),
                    ),
                )
            )
            applied_steps.append(
                {
                    "step": step_name,
                    "from": current_ext,
                    "to": current_ext,
                    "input_path": str(current_path),
                    "output_path": str(output_path),
                }
            )
            current_path = output_path

        # Uniform structural validation, before any method-specific handling
        # and before dispatch. Runs for all four methods so the same defect is
        # rejected identically whichever tool the user picked.
        #
        # It inspects rather than transforms, so it logs but is deliberately
        # kept out of `applied_steps` and out of the step numbering — both of
        # which describe the conversion chain.
        step_name = "validate_input_table"
        try:
            validation_stats = validate_airr_table(
                current_path,
                delimiter="," if current_ext == "csv" else "\t",
                **_validation_columns(method, params),
            )
        except InputValidationError as exc:
            raise PreprocessError(
                code=exc.code,
                message=exc.message,
                details={
                    "method_id": method,
                    "step": step_name,
                    **exc.details,
                    "next_actions": ["Correct the input table and re-upload it."],
                },
            ) from exc

        stats["input_validation"] = validation_stats
        log_entries.append(
            _preprocess_log(
                step_name,
                "file={name}; rows={rows} columns={cols}; alignment length={length}"
                "{ragged}; id column='{idc}' sequence column='{seqc}'; "
                "checks passed={checks}".format(
                    name=current_path.name,
                    rows=validation_stats["rows"],
                    cols=validation_stats["columns"],
                    length=validation_stats["alignment_length"],
                    ragged=(
                        " (modal; {n} distinct lengths)".format(
                            n=validation_stats["distinct_alignment_lengths"]
                        )
                        if validation_stats["distinct_alignment_lengths"] > 1
                        else ""
                    ),
                    idc=validation_stats["id_column"],
                    seqc=validation_stats["sequence_column"],
                    checks=len(validation_stats["checked"]),
                ),
            )
        )
    if should_apply_column_mapping(method, current_ext, params):
        required_keys = active_required_keys(method, params)
        if current_ext not in TABULAR_EXTENSIONS:
            raise _conversion_error(
                method_id=method,
                input_ext=current_ext,
                message="Column mapping is only supported for CSV/TSV tabular inputs.",
                code="UNSUPPORTED_INPUT",
                step="rename_table_columns",
            )

        step_offset += 1
        step_name = "rename_table_columns"
        output_path = work_dir / f"{step_offset:02d}_{step_name}.{current_ext}"
        step_report: dict[str, Any] = {
            "step": step_name,
            "from": current_ext,
            "to": current_ext,
        }
        column_map = _get_column_map(params)
        delimiter: Literal["csv", "tsv"] = "csv" if current_ext == "csv" else "tsv"

        try:
            rename_stats = rename_table_columns(
                current_path,
                output_path,
                delimiter=delimiter,
                normalize_headers=True,
                column_map=column_map,
                required_keys=required_keys,
            )
            stats[f"step_{step_offset}_table"] = {
                "rows": rename_stats.get("rows", 0),
                "cols": rename_stats.get("cols", 0),
                "resolved_map": rename_stats.get("resolved_map", {}),
            }
            for warning in rename_stats.get("warnings", []):
                warnings.append({"code": "TABLE_RENAME_WARNING", "message": str(warning)})
            # `resolved_map` is canonical_key -> the source header it resolved
            # to, so the rename reads source -> canonical in the log.
            resolved_map = rename_stats.get("resolved_map") or {}
            renames = [
                f"{source}->{canonical}"
                for canonical, source in resolved_map.items()
                if source and source != canonical
            ]
            unchanged = sum(
                1 for canonical, source in resolved_map.items() if source == canonical
            )
            log_entries.append(
                _preprocess_log(
                    step_name,
                    "file={name}; columns renamed={n_renamed} [{renames}]; "
                    "already canonical={n_same}; rows={rows} columns={cols}"
                    "{warn}".format(
                        name=current_path.name,
                        n_renamed=len(renames),
                        renames=", ".join(renames) if renames else "none",
                        n_same=unchanged,
                        rows=rename_stats.get("rows", 0),
                        cols=rename_stats.get("cols", 0),
                        warn=_fmt_step_warnings(rename_stats.get("warnings")),
                    ),
                )
            )
        except ConversionError as exc:
            if exc.code == "MISSING_REQUIRED_MAPPING":
                raise _missing_mapping_error(
                    method_id=method,
                    input_ext=current_ext,
                    required_keys=required_keys,
                    column_map=column_map,
                    converter_error=exc,
                    step=step_name,
                ) from exc

            mapped_code = "INVALID_FILE" if exc.code in INVALID_FILE_CONVERTER_CODES else "CONVERSION_FAILED"
            raise _conversion_error(
                method_id=method,
                input_ext=current_ext,
                message=_column_mapping_step_message(exc, column_map=column_map, step=step_name),
                converter_error=exc,
                code=mapped_code,
                step=step_name,
                extra_details={
                    "column_map": column_map,
                    "input_columns": _string_list(exc.details.get("available_columns")),
                },
            ) from exc

        step_report["input_path"] = str(current_path)
        step_report["output_path"] = str(output_path)
        applied_steps.append(step_report)
        current_path = output_path
        mapping_applied = True

    if is_native_accept(method, current_ext):  # type: ignore[arg-type]
        if current_ext in TABULAR_EXTENSIONS:
            try:
                stats["input_table"] = _table_stats(current_path, current_ext)
            except Exception:
                pass
        log_entries.append(
            _summary_log(
                method=method,
                applied_steps=applied_steps,
                input_ext=normalized_ext,
                final_ext=current_ext,
                note="no format conversion required",
            )
        )
        return PreparedInput(
            final_path=current_path,
            final_ext=current_ext,
            applied_steps=applied_steps,
            warnings=warnings,
            stats=stats,
            log_entries=log_entries,
        )

    chain = safe_conversion_chain(method, current_ext)  # type: ignore[arg-type]
    if not chain:
        raise _unsupported_input_error(method, current_ext)

    for index, step in enumerate(chain, start=step_offset + 1):
        step_name = str(step["step"])
        target_ext = normalize_extension(str(step["to"]))
        step_report: dict[str, Any] = {
            "step": step_name,
            "from": current_ext,
            "to": target_ext,
        }
        output_path = work_dir / f"{index:02d}_{step_name}.{target_ext}"

        try:
            if step_name == "convert_csv_to_tsv":
                convert_csv_to_tsv(current_path, output_path)
                stats[f"step_{index}_table"] = _table_stats(output_path, "tsv")
                log_entries.append(
                    _preprocess_log(
                        step_name,
                        "file={name}; converted CSV -> TSV; "
                        "result=.{ext} rows={rows} columns={cols}".format(
                            name=current_path.name,
                            ext=target_ext,
                            rows=stats[f"step_{index}_table"].get("rows", 0),
                            cols=stats[f"step_{index}_table"].get("cols", 0),
                        ),
                    )
                )
            elif step_name == "convert_tsv_to_csv":
                convert_tsv_to_csv(current_path, output_path)
                stats[f"step_{index}_table"] = _table_stats(output_path, "csv")
                log_entries.append(
                    _preprocess_log(
                        step_name,
                        "file={name}; converted TSV -> CSV; "
                        "result=.{ext} rows={rows} columns={cols}".format(
                            name=current_path.name,
                            ext=target_ext,
                            rows=stats[f"step_{index}_table"].get("rows", 0),
                            cols=stats[f"step_{index}_table"].get("cols", 0),
                        ),
                    )
                )
            elif step_name == "convert_table_to_aligned_fasta":
                delimiter: Literal["csv", "tsv"] | None
                if current_ext == "csv":
                    delimiter = "csv"
                elif current_ext == "tsv":
                    delimiter = "tsv"
                else:
                    delimiter = None

                if method == "gctree" and mapping_applied and current_ext in TABULAR_EXTENSIONS:
                    aligned_seq_column = GCTREE_ALIGNED_COLUMN_DEFAULT
                    id_column = CANONICAL_SEQUENCE_ID_KEY
                else:
                    aligned_seq_column = _gctree_aligned_seq_column(params)
                    id_column = _gctree_id_column(params)
                conversion_stats = convert_table_to_aligned_fasta(
                    current_path,
                    output_path,
                    id_column=id_column,
                    aligned_seq_column=aligned_seq_column,
                    delimiter=delimiter,
                )
                stats[f"step_{index}_fasta"] = conversion_stats
                for warning in conversion_stats.get("warnings", []):
                    if isinstance(warning, dict):
                        warnings.append(warning)
                    else:
                        warnings.append(
                            {"code": "UNEXPECTED_ALIGNMENT_CHARACTER", "message": warning}
                        )
                log_entries.append(
                    _preprocess_log(
                        step_name,
                        "file={name}; exported table -> aligned FASTA "
                        "(id column={id_col}, aligned sequence column={seq_col}); "
                        "result=.{ext} records={n} alignment length={length}"
                        "{warn}".format(
                            name=current_path.name,
                            id_col=conversion_stats.get("used_id_column"),
                            seq_col=conversion_stats.get("used_aligned_seq_column"),
                            ext=target_ext,
                            n=conversion_stats.get("n_records", 0),
                            length=conversion_stats.get("alignment_length"),
                            warn=_fmt_step_warnings(conversion_stats.get("warnings")),
                        ),
                    )
                )
            else:
                raise PreprocessError(
                    code="CONVERSION_FAILED",
                    message=f"Unknown conversion step '{step_name}'.",
                    details={"method_id": method, "input_ext": current_ext},
                )
        except ConversionError as exc:
            if (
                method == "gctree"
                and step_name == "convert_table_to_aligned_fasta"
                and exc.code in GCTREE_IDENTIFIER_CONVERTER_CODES
            ):
                details = exc.details or {}
                if exc.code == "DUPLICATE_IDS":
                    message = (
                        "GCtree converts the table to FASTA, where every record header must "
                        "be unique, but identifier {id!r} appears on rows {first} and {second}."
                    ).format(
                        id=details.get("id"),
                        first=details.get("first_row_number"),
                        second=details.get("duplicate_row_number"),
                    )
                else:
                    message = (
                        "GCtree converts the table to FASTA, where every record needs a header, "
                        "but column '{column}' is empty on row {row}."
                    ).format(
                        column=details.get("id_column"),
                        row=details.get("row_number"),
                    )
                raise _conversion_error(
                    method_id=method,
                    input_ext=current_ext,
                    message=message,
                    converter_error=exc,
                    code=exc.code,
                    step=step_name,
                ) from exc
            if (
                method == "gctree"
                and step_name == "convert_table_to_aligned_fasta"
                and exc.code in GCTREE_ALIGNMENT_CONVERTER_CODES
            ):
                raise _conversion_error(
                    method_id=method,
                    input_ext=current_ext,
                    message=(
                        "GCtree tabular input requires an existing aligned sequence column "
                        "with non-empty, equal-length alignment strings."
                    ),
                    converter_error=exc,
                    code="GCTREE_ALIGNMENT_REQUIRED",
                    step=step_name,
                ) from exc
            mapped_code = "INVALID_FILE" if exc.code in INVALID_FILE_CONVERTER_CODES else "CONVERSION_FAILED"
            raise _conversion_error(
                method_id=method,
                input_ext=current_ext,
                message=f"Safe conversion failed at step '{step_name}'.",
                converter_error=exc,
                code=mapped_code,
                step=step_name,
            ) from exc

        step_report["input_path"] = str(current_path)
        step_report["output_path"] = str(output_path)
        applied_steps.append(step_report)
        current_path = output_path
        current_ext = target_ext

    log_entries.append(
        _summary_log(
            method=method,
            applied_steps=applied_steps,
            input_ext=normalized_ext,
            final_ext=current_ext,
            note="safe conversion chain applied",
        )
    )
    return PreparedInput(
        final_path=current_path,
        final_ext=current_ext,
        applied_steps=applied_steps,
        warnings=warnings,
        stats=stats,
        log_entries=log_entries,
    )
