"""Universal structural validation of a tabular input, before dispatch.

Runs in the orchestrator for every method, so a table that no method could make
sense of is rejected once, in one place, with one message — instead of failing
four different ways downstream.

Scope is deliberately narrow. A check belongs here only if it is invalid for
**every** method regardless of configuration: a missing identifier column, an
empty identifier, an empty sequence, a character that is not a nucleotide. Those
are properties of the table, not of the analysis.

Checks whose answer depends on the method or its parameters stay with the method
that owns the contract, and are **not** implemented here. Two in particular, both
documented in `docs/validation-coverage.md`:

  * **Alignment-length equality.** Fatal for Dowser and GCtree, which consume a
    fixed-width alignment. Not fatal for ClonalTree without `use_input_alignment`
    (MUSCLE re-aligns) or for BrepPhylo in its default `raw_sequence` mode
    (Clustal re-aligns). Each service applies its own condition.
  * **Identifier uniqueness.** Global for Dowser, GCtree and ClonalTree; scoped
    to a clone for BrepPhylo, which builds per-clone trees. All four already
    enforce it in-service.

Messages name the actual cause and, where it is knowable, the offending rows,
identifiers, or characters. A reported row number is the true 1-based line number
of the uploaded file — which is what a spreadsheet shows in its row gutter — so it
stays correct even when blank padding rows sit between records.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable, Literal

# Gaps use both IMGT ('.') and conventional ('-') conventions. Ambiguity codes
# are the full IUPAC nucleotide set: rejecting them would throw out valid AIRR
# data, and 'N' in particular is needed by the germline row that the GCtree
# evaluation input carries.
GAP_CHARS = frozenset(".-")
IUPAC_NUCLEOTIDES = frozenset("ACGTURYSWKMBDHVN")
ALLOWED_SEQUENCE_CHARS = frozenset(
    {c.lower() for c in IUPAC_NUCLEOTIDES} | set(IUPAC_NUCLEOTIDES) | GAP_CHARS
)

# How many offending items to name before truncating a message.
_MAX_LISTED = 10


class InputValidationError(Exception):
    """A structural defect that must stop the run before dispatch."""

    def __init__(self, code: str, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details or {}

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "details": self.details}


def _listed(items: Iterable[Any]) -> str:
    items = list(items)
    shown = ", ".join(str(i) for i in items[:_MAX_LISTED])
    extra = len(items) - _MAX_LISTED
    return f"{shown} (and {extra} more)" if extra > 0 else shown


def _is_blank(row: list[str]) -> bool:
    return all(not (cell or "").strip() for cell in row)


def _read_numbered_rows(path: Path, delimiter: str) -> list[tuple[int, list[str]]]:
    """Rows paired with their true 1-based line number in the file.

    Carrying the line number through means a blank padding row between records
    does not shift every subsequent number in an error message.
    """
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(enumerate(csv.reader(handle, delimiter=delimiter), start=1))


def validate_airr_table(
    path: Path,
    *,
    delimiter: Literal[",", "\t"] = "\t",
    required_columns: Iterable[str] = (),
    id_column: str = "sequence_id",
    sequence_column: str = "sequence_alignment",
) -> dict[str, Any]:
    """Validate one tabular input, raising `InputValidationError` on the first
    structural defect found.

    Returns a small summary on success so the caller can log what was checked.
    """
    required = [c for c in dict.fromkeys(required_columns) if c]

    # 1. Completely empty file --------------------------------------------
    try:
        if path.stat().st_size == 0:
            raise InputValidationError(
                code="INPUT_EMPTY_FILE",
                message="The input file is empty (0 bytes). Upload a table with a header row and at least one data row.",
                details={"path": path.name},
            )
    except OSError as exc:
        raise InputValidationError(
            code="INPUT_UNREADABLE",
            message=f"The input file could not be read: {exc}",
            details={"path": path.name},
        ) from exc

    numbered = _read_numbered_rows(path, delimiter)
    if not numbered or all(_is_blank(row) for _, row in numbered):
        raise InputValidationError(
            code="INPUT_EMPTY_FILE",
            message="The input file contains no readable rows. Upload a table with a header row and at least one data row.",
            details={"path": path.name},
        )

    header = [(cell or "").strip() for cell in numbered[0][1]]
    if not any(header):
        raise InputValidationError(
            code="INPUT_NO_HEADER",
            message="The input file has no header row. The first row must name the columns.",
            details={"path": path.name},
        )

    # Blank padding rows are dropped, but every surviving row keeps the line
    # number it actually occupies in the file.
    body = [(line, row) for line, row in numbered[1:] if not _is_blank(row)]

    # 2. Header-only file --------------------------------------------------
    if not body:
        raise InputValidationError(
            code="INPUT_NO_DATA_ROWS",
            message=(
                f"The input file has a header row but no data rows. "
                f"Found {len(header)} column(s) and 0 sequences."
            ),
            details={"path": path.name, "columns": len(header), "data_rows": 0},
        )

    # 3. Required columns present -----------------------------------------
    # The id and sequence columns are always structurally required: every check
    # below reads them, and no method can proceed without them.
    expected = list(dict.fromkeys([*required, id_column, sequence_column]))
    missing = [c for c in expected if c not in header]
    if missing:
        raise InputValidationError(
            code="INPUT_MISSING_COLUMNS",
            message=(
                f"The input table is missing {len(missing)} required column(s): {_listed(missing)}. "
                f"Found columns: {_listed(header)}."
            ),
            details={"missing_columns": missing, "found_columns": header},
        )

    id_index = header.index(id_column)
    seq_index = header.index(sequence_column)

    def cell(row: list[str], index: int) -> str:
        return (row[index] or "").strip() if index < len(row) else ""

    # 4. Empty sequence_id -------------------------------------------------
    empty_ids = [line for line, row in body if not cell(row, id_index)]
    if empty_ids:
        raise InputValidationError(
            code="INPUT_EMPTY_SEQUENCE_ID",
            message=(
                f"Column '{id_column}' is empty in {len(empty_ids)} row(s): "
                f"row {_listed(empty_ids)}. Every sequence needs a non-empty identifier."
            ),
            details={"id_column": id_column, "lines": empty_ids},
        )

    # 5. Empty sequence ----------------------------------------------------
    empty_seqs = [line for line, row in body if not cell(row, seq_index)]
    if empty_seqs:
        raise InputValidationError(
            code="INPUT_EMPTY_SEQUENCE",
            message=(
                f"Column '{sequence_column}' is empty in {len(empty_seqs)} row(s): "
                f"row {_listed(empty_seqs)}. Every sequence needs an alignment string."
            ),
            details={"sequence_column": sequence_column, "lines": empty_seqs},
        )

    # 6. Invalid nucleotide characters ------------------------------------
    # Reported together across the table, so one pass names every offending
    # character rather than stopping at the first row.
    offending: dict[str, list[int]] = {}
    for line, row in body:
        for char in set(cell(row, seq_index)) - ALLOWED_SEQUENCE_CHARS:
            offending.setdefault(char, []).append(line)
    if offending:
        chars = sorted(offending)
        lines_named = sorted({n for ns in offending.values() for n in ns})
        raise InputValidationError(
            code="INPUT_INVALID_SEQUENCE_CHARACTERS",
            message=(
                f"Column '{sequence_column}' contains {len(chars)} character(s) that are not "
                f"nucleotides or gaps: {_listed(chars)}. "
                f"Affected row(s): {_listed(lines_named)}. "
                "Allowed characters are A, C, G, T, U, the IUPAC ambiguity codes, and the gap characters '.' and '-'."
            ),
            details={
                "sequence_column": sequence_column,
                "invalid_characters": chars,
                "lines": lines_named,
            },
        )

    lengths: dict[int, list[int]] = {}
    for line, row in body:
        lengths.setdefault(len(cell(row, seq_index)), []).append(line)

    return {
        "rows": len(body),
        "columns": len(header),
        # Reported, not enforced: whether ragged input is acceptable is the
        # method's decision, so this is information for the log only.
        "alignment_length": max(lengths, key=lambda k: len(lengths[k])),
        "distinct_alignment_lengths": len(lengths),
        "id_column": id_column,
        "sequence_column": sequence_column,
        "checked": [
            "empty_file",
            "header_present",
            "data_rows_present",
            "required_columns",
            "empty_sequence_id",
            "empty_sequence",
            "invalid_sequence_characters",
        ],
    }
