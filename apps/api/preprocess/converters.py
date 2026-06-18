from __future__ import annotations

import csv
import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger(__name__)

ID_COLUMN_SYNONYMS = ("sequence_id", "seq_id", "id", "name")
ALLOWED_ALIGNMENT_CHARS = set("ACGTNacgtn-.*?")

# Delimiters we attempt to detect when an input file's actual separator is unknown.
# Order matters only for the tie-break behavior below.
CANDIDATE_TABLE_DELIMITERS = ("\t", ",", ";")


@dataclass
class ConversionError(Exception):
    code: str
    message: str
    details: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
        }


def normalize_header(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.strip().lower())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized


def canonical_delimiter_for_extension(ext: str) -> str:
    normalized = ext.lower().lstrip(".")
    return "\t" if normalized in {"tsv", "tab"} else ","


def _sniff_delimiter_from_header(input_path: Path, fallback: str) -> str:
    try:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            header = handle.readline()
    except OSError as exc:
        raise ConversionError(
            code="READ_ERROR",
            message="Failed to read input table.",
            details={"input_path": str(input_path), "error": str(exc)},
        ) from exc

    counts = {char: header.count(char) for char in CANDIDATE_TABLE_DELIMITERS}
    best_char = max(CANDIDATE_TABLE_DELIMITERS, key=lambda char: counts[char])
    if counts[best_char] > 0:
        return best_char
    return fallback


def _table_delimiter(
    input_path: Path, delimiter: Literal["csv", "tsv"] | None = None
) -> str:
    # TSV is unambiguous — trust the hint or the extension and skip sniffing.
    if delimiter == "tsv":
        return "\t"
    suffix = input_path.suffix.lower()
    if delimiter is None and suffix in {".tsv", ".tab"}:
        return "\t"

    # For CSV-family inputs always sniff the header so we catch semicolon-
    # separated exports (common from Excel / European locales) instead of
    # silently treating them as a single-column comma file.
    fallback = "\t" if suffix in {".tsv", ".tab"} else ","
    return _sniff_delimiter_from_header(input_path, fallback=fallback)


def _row_is_blank(row: list[str]) -> bool:
    """True when every cell in the row is empty or whitespace-only."""
    return all(not cell or not cell.strip() for cell in row)


def _read_table(
    input_path: Path, delimiter_char: str
) -> tuple[list[str], list[list[str]], int]:
    try:
        # utf-8-sig transparently strips a leading UTF-8 BOM from the first
        # cell of the first row, so headers like '﻿sequence_id' do not
        # leak through and break downstream column matching.
        with input_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle, delimiter=delimiter_char)
            rows = list(reader)
    except OSError as exc:
        raise ConversionError(
            code="READ_ERROR",
            message="Failed to read input table.",
            details={"input_path": str(input_path), "error": str(exc)},
        ) from exc
    except csv.Error as exc:
        raise ConversionError(
            code="PARSE_ERROR",
            message="Failed to parse input table.",
            details={"input_path": str(input_path), "error": str(exc)},
        ) from exc

    if not rows:
        raise ConversionError(
            code="EMPTY_TABLE",
            message="Input table is empty.",
            details={"input_path": str(input_path)},
        )

    header = rows[0]
    # Drop fully-blank rows (e.g. `;;;;;;...`). Excel commonly pads exports
    # with trailing empty rows extending the "used range"; passing them
    # through would later be rejected by validators as empty sequence_id /
    # clone_id rows.
    body: list[list[str]] = []
    blank_rows_dropped = 0
    expected_cols = len(header)
    for row_number, row in enumerate(rows[1:], start=2):
        if len(row) != expected_cols:
            raise ConversionError(
                code="ROW_WIDTH_MISMATCH",
                message=(
                    f"Input table has inconsistent row widths: row {row_number} "
                    f"has {len(row)} column(s) but the header has {expected_cols}."
                ),
                details={
                    "input_path": str(input_path),
                    "row_number": row_number,
                    "expected_columns": expected_cols,
                    "actual_columns": len(row),
                },
            )
        if _row_is_blank(row):
            blank_rows_dropped += 1
            continue
        body.append(row)

    return header, body, blank_rows_dropped


def _write_table(
    output_path: Path,
    delimiter_char: str,
    header: list[str],
    body: list[list[str]],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(
                handle,
                delimiter=delimiter_char,
                quoting=csv.QUOTE_MINIMAL,
                lineterminator="\n",
            )
            writer.writerow(header)
            writer.writerows(body)
    except OSError as exc:
        raise ConversionError(
            code="WRITE_ERROR",
            message="Failed to write converted table.",
            details={"output_path": str(output_path), "error": str(exc)},
        ) from exc


def _resolve_column_name(
    header: list[str],
    requested: str,
    *,
    normalize_headers: bool,
    required: bool = True,
) -> str | None:
    if requested in header:
        return requested

    if normalize_headers:
        requested_normalized = normalize_header(requested)
        normalized_matches = [
            original for original in header if normalize_header(original) == requested_normalized
        ]
        if len(normalized_matches) == 1:
            return normalized_matches[0]
        if len(normalized_matches) > 1:
            raise ConversionError(
                code="AMBIGUOUS_COLUMN",
                message=f"Column '{requested}' matches multiple headers after normalization.",
                details={"requested_column": requested, "matches": normalized_matches},
            )

    if required:
        raise ConversionError(
            code="COLUMN_NOT_FOUND",
            message=f"Column '{requested}' was not found in the input table.",
            details={"requested_column": requested, "available_columns": header},
        )
    return None


def _pick_id_column(
    header: list[str],
    id_column: str | None,
    *,
    normalize_headers: bool,
) -> str:
    if id_column:
        resolved = _resolve_column_name(
            header,
            id_column,
            normalize_headers=normalize_headers,
            required=True,
        )
        assert resolved is not None
        return resolved

    for candidate in ID_COLUMN_SYNONYMS:
        resolved = _resolve_column_name(
            header,
            candidate,
            normalize_headers=normalize_headers,
            required=False,
        )
        if resolved is not None:
            return resolved

    return header[0]


def convert_tsv_to_csv(input_path: Path, output_path: Path) -> None:
    header, body, _ = _read_table(input_path, delimiter_char="\t")
    _write_table(output_path, delimiter_char=",", header=header, body=body)
    logger.info(
        "Converted TSV to CSV",
        extra={"rows": len(body), "columns": len(header), "input_path": str(input_path)},
    )


def convert_csv_to_tsv(input_path: Path, output_path: Path) -> None:
    delimiter_char = _table_delimiter(input_path, delimiter="csv")
    header, body, _ = _read_table(input_path, delimiter_char=delimiter_char)
    _write_table(output_path, delimiter_char="\t", header=header, body=body)
    logger.info(
        "Converted CSV to TSV",
        extra={"rows": len(body), "columns": len(header), "input_path": str(input_path)},
    )


def normalize_table_delimiter(
    input_path: Path,
    output_path: Path,
    *,
    delimiter: Literal["csv", "tsv"] | None = None,
) -> dict[str, Any]:
    """Rewrite a tabular file using the canonical delimiter for its extension.

    Auto-detects the actual delimiter (handles semicolon-CSV exports) so that
    downstream consumers can rely on plain comma/tab separators regardless of
    the original locale-specific formatting of the upload. Also strips any
    UTF-8 BOM and drops fully-blank padding rows that Excel often emits.
    """
    detected_char = _table_delimiter(input_path, delimiter=delimiter)
    header, body, blank_rows_dropped = _read_table(
        input_path, delimiter_char=detected_char
    )
    output_ext = output_path.suffix.lower().lstrip(".") or (
        "tsv" if detected_char == "\t" else "csv"
    )
    output_char = canonical_delimiter_for_extension(output_ext)
    _write_table(output_path, delimiter_char=output_char, header=header, body=body)
    return {
        "rows": len(body),
        "cols": len(header),
        "input_delimiter": detected_char,
        "output_delimiter": output_char,
        "blank_rows_dropped": blank_rows_dropped,
    }


def rename_table_columns(
    input_path: Path,
    output_path: Path,
    *,
    delimiter: Literal["csv", "tsv"] | None = None,
    normalize_headers: bool = True,
    column_map: dict[str, str],
    required_keys: list[str],
    allow_missing_optional: bool = True,
) -> dict[str, Any]:
    # Reserved for future optional-key support while keeping a stable function signature.
    _ = allow_missing_optional

    delimiter_char = _table_delimiter(input_path, delimiter=delimiter)
    header, body, blank_rows_dropped = _read_table(
        input_path, delimiter_char=delimiter_char
    )
    if not header:
        raise ConversionError(
            code="EMPTY_HEADER",
            message="Input table has no header row.",
            details={"input_path": str(input_path)},
        )

    cleaned_map: dict[str, str] = {}
    for canonical_key, mapped_value in (column_map or {}).items():
        if not isinstance(canonical_key, str) or not isinstance(mapped_value, str):
            continue
        canonical_clean = canonical_key.strip()
        mapped_clean = mapped_value.strip()
        if canonical_clean and mapped_clean:
            cleaned_map[canonical_clean] = mapped_clean

    resolved_map: dict[str, str] = {}

    for canonical_key, requested_column in cleaned_map.items():
        resolved = _resolve_column_name(
            header,
            requested_column,
            normalize_headers=normalize_headers,
            required=True,
        )
        assert resolved is not None
        if resolved in resolved_map.values():
            duplicate_with = next(
                key for key, resolved_name in resolved_map.items() if resolved_name == resolved
            )
            raise ConversionError(
                code="AMBIGUOUS_COLUMN",
                message="Multiple canonical keys resolve to the same source column.",
                details={
                    "source_column": resolved,
                    "canonical_keys": [duplicate_with, canonical_key],
                },
            )
        resolved_map[canonical_key] = resolved

    renamed_header = list(header)
    for canonical_key, source_column in resolved_map.items():
        source_index = header.index(source_column)
        renamed_header[source_index] = canonical_key

    duplicates = sorted([name for name, count in Counter(renamed_header).items() if count > 1])
    if duplicates:
        raise ConversionError(
            code="AMBIGUOUS_COLUMN",
            message="Renaming would create duplicate target headers.",
            details={
                "duplicated_headers": duplicates,
                "resolved_map": resolved_map,
                "original_header": header,
            },
        )

    missing_required_keys: list[str] = []
    for canonical_key in required_keys:
        resolved = _resolve_column_name(
            renamed_header,
            canonical_key,
            normalize_headers=normalize_headers,
            required=False,
        )
        if resolved is None:
            missing_required_keys.append(canonical_key)

    if missing_required_keys:
        raise ConversionError(
            code="MISSING_REQUIRED_MAPPING",
            message="Missing required columns after applying column mapping.",
            details={
                "missing_required_keys": missing_required_keys,
                "required_keys": required_keys,
                "available_columns": header,
                "renamed_columns": renamed_header,
                "resolved_map": resolved_map,
            },
        )

    output_ext = output_path.suffix.lower().lstrip(".") or (
        "tsv" if delimiter_char == "\t" else "csv"
    )
    output_delimiter_char = canonical_delimiter_for_extension(output_ext)
    _write_table(
        output_path=output_path,
        delimiter_char=output_delimiter_char,
        header=renamed_header,
        body=body,
    )

    return {
        "resolved_map": resolved_map,
        "rows": len(body),
        "cols": len(renamed_header),
        "input_delimiter": delimiter_char,
        "output_delimiter": output_delimiter_char,
        "blank_rows_dropped": blank_rows_dropped,
        "warnings": [],
    }


def convert_table_to_aligned_fasta(
    input_path: Path,
    output_path: Path,
    *,
    id_column: str | None = None,
    aligned_seq_column: str,
    delimiter: Literal["csv", "tsv"] | None = None,
    normalize_headers: bool = True,
) -> dict[str, Any]:
    if not aligned_seq_column or not aligned_seq_column.strip():
        raise ConversionError(
            code="INVALID_ALIGNED_COLUMN",
            message="aligned_seq_column must be provided.",
            details={},
        )

    delimiter_char = _table_delimiter(input_path, delimiter=delimiter)
    header, body, _ = _read_table(input_path, delimiter_char=delimiter_char)
    if not header:
        raise ConversionError(
            code="EMPTY_HEADER",
            message="Input table has no header row.",
            details={"input_path": str(input_path)},
        )

    used_aligned_seq_column = _resolve_column_name(
        header,
        aligned_seq_column,
        normalize_headers=normalize_headers,
        required=True,
    )
    assert used_aligned_seq_column is not None
    used_id_column = _pick_id_column(header, id_column, normalize_headers=normalize_headers)

    id_index = header.index(used_id_column)
    sequence_index = header.index(used_aligned_seq_column)

    warnings: list[str] = []
    unique_ids: dict[str, int] = {}
    alignment_length: int | None = None
    records: list[tuple[str, str]] = []

    for row_offset, row in enumerate(body):
        row_number = row_offset + 2
        record_id = row[id_index]
        if record_id == "":
            raise ConversionError(
                code="EMPTY_ID",
                message="ID column contains an empty value.",
                details={
                    "row_number": row_number,
                    "id_column": used_id_column,
                },
            )
        if record_id in unique_ids:
            raise ConversionError(
                code="DUPLICATE_IDS",
                message="Duplicate FASTA identifiers are not allowed.",
                details={
                    "id": record_id,
                    "first_row_number": unique_ids[record_id],
                    "duplicate_row_number": row_number,
                },
            )
        unique_ids[record_id] = row_number

        sequence_value = row[sequence_index].strip()
        if sequence_value == "":
            raise ConversionError(
                code="MISSING_ALIGNED_SEQUENCE",
                message="Aligned sequence column contains an empty value.",
                details={
                    "row_number": row_number,
                    "aligned_seq_column": used_aligned_seq_column,
                },
            )

        current_length = len(sequence_value)
        if alignment_length is None:
            alignment_length = current_length
        elif current_length != alignment_length:
            raise ConversionError(
                code="ALIGNMENT_LENGTH_MISMATCH",
                message="All aligned sequences must have the same length.",
                details={
                    "row_number": row_number,
                    "expected_length": alignment_length,
                    "actual_length": current_length,
                },
            )

        unexpected_chars = sorted({char for char in sequence_value if char not in ALLOWED_ALIGNMENT_CHARS})
        if unexpected_chars:
            warnings.append(
                f"Row {row_number} contains unexpected alignment characters: {''.join(unexpected_chars)}"
            )

        records.append((record_id, sequence_value))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("w", encoding="utf-8", newline="") as handle:
            for record_id, aligned_sequence in records:
                handle.write(f">{record_id}\n")
                handle.write(f"{aligned_sequence}\n")
    except OSError as exc:
        raise ConversionError(
            code="WRITE_ERROR",
            message="Failed to write FASTA output.",
            details={"output_path": str(output_path), "error": str(exc)},
        ) from exc

    return {
        "n_records": len(records),
        "alignment_length": alignment_length or 0,
        "used_id_column": used_id_column,
        "used_aligned_seq_column": used_aligned_seq_column,
        "warnings": warnings,
    }
