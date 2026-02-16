from __future__ import annotations

import csv
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

from apps.api.preprocess.converters import (
    ConversionError,
    convert_csv_to_tsv,
    convert_table_to_aligned_fasta,
    convert_tsv_to_csv,
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

    if is_native_accept(method, normalized_ext):  # type: ignore[arg-type]
        if normalized_ext in TABULAR_EXTENSIONS:
            try:
                stats["input_table"] = _table_stats(uploaded_path, normalized_ext)
            except Exception:
                pass
        return PreparedInput(
            final_path=uploaded_path,
            final_ext=normalized_ext,
            applied_steps=applied_steps,
            warnings=warnings,
            stats=stats,
        )

    chain = safe_conversion_chain(method, normalized_ext)  # type: ignore[arg-type]
    if not chain:
        raise _unsupported_input_error(method, normalized_ext)

    current_path = uploaded_path
    current_ext = normalized_ext

    for index, step in enumerate(chain, start=1):
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
