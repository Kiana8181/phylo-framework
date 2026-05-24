from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from apps.api.preprocess.column_requirements import (
    CLONALTREE_ALIGNMENT_REQUIRED_KEYS,
    CLONALTREE_BASE_REQUIRED_KEYS,
    CLONALTREE_REFINEMENT_REQUIRED_KEYS,
    DOWSER_HL_REQUIRED_KEYS,
    DOWSER_REQUIRED_KEYS,
    REQUIRED_KEYS_BY_METHOD,
)
from apps.api.preprocess.converters import (
    ConversionError,
    convert_csv_to_tsv,
    convert_table_to_aligned_fasta,
    convert_tsv_to_csv,
    rename_table_columns,
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
    "EMPTY_ID",
    "DUPLICATE_IDS",
}


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

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["final_path"] = str(self.final_path)
        return payload


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


def active_required_keys(method_id: str, params: dict[str, Any]) -> list[str]:
    method = method_id.lower().strip()
    if method == "clonaltree":
        required = list(CLONALTREE_BASE_REQUIRED_KEYS)
        if _uses_clonaltree_refinement(params):
            required.extend(CLONALTREE_REFINEMENT_REQUIRED_KEYS)
        required.extend(CLONALTREE_ALIGNMENT_REQUIRED_KEYS)
        return required
    if method == "dowser":
        required = list(DOWSER_REQUIRED_KEYS)
        chain_mode = str(params.get("chain_mode") or "H").strip().upper()
        if chain_mode == "HL":
            required.extend(DOWSER_HL_REQUIRED_KEYS)
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


def _table_stats(path: Path, ext: str) -> dict[str, int]:
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


def _conversion_error(
    method_id: str,
    input_ext: str,
    message: str,
    converter_error: ConversionError | None = None,
    *,
    code: str = "CONVERSION_FAILED",
    step: str | None = None,
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
    missing_keys = converter_error.details.get("missing_required_keys")
    missing = missing_keys if isinstance(missing_keys, list) else []
    example_mapping = {key: f"<column for {key}>" for key in required_keys}
    return PreprocessError(
        code="MISSING_COLUMN_MAPPING",
        message="Input is missing one or more required columns after column mapping.",
        details={
            "method_id": method_id,
            "input_ext": input_ext,
            "step": step,
            "required_keys": required_keys,
            "missing_keys": missing,
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
    current_path = uploaded_path
    current_ext = normalized_ext
    step_offset = 0
    mapping_applied = False

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
                message=f"Safe conversion failed at step '{step_name}'.",
                converter_error=exc,
                code=mapped_code,
                step=step_name,
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
        return PreparedInput(
            final_path=current_path,
            final_ext=current_ext,
            applied_steps=applied_steps,
            warnings=warnings,
            stats=stats,
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
            elif step_name == "convert_tsv_to_csv":
                convert_tsv_to_csv(current_path, output_path)
                stats[f"step_{index}_table"] = _table_stats(output_path, "csv")
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
                    warnings.append({"code": "UNEXPECTED_ALIGNMENT_CHARACTER", "message": warning})
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

    return PreparedInput(
        final_path=current_path,
        final_ext=current_ext,
        applied_steps=applied_steps,
        warnings=warnings,
        stats=stats,
    )
