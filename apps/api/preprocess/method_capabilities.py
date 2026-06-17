from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Literal

MethodId = Literal["dowser", "brepphylo", "clonaltree", "gctree"]

DOWSER_ACCEPTS = {"tsv", "csv", "rda", "rds"}
BREPPHYLO_ACCEPTS = {"tsv", "csv"}
CLONALTREE_ACCEPTS = {"tsv"}
GCTREE_ACCEPTS = {"fasta", "fa", "fna", "p", "zip"}

NATIVE_ACCEPTS_BY_METHOD: dict[MethodId, set[str]] = {
    "dowser": DOWSER_ACCEPTS,
    "brepphylo": BREPPHYLO_ACCEPTS,
    "clonaltree": CLONALTREE_ACCEPTS,
    "gctree": GCTREE_ACCEPTS,
}

# Conversion steps are intentionally limited to format/container changes only.
SAFE_CONVERSION_PATHS: dict[MethodId, dict[str, list[dict[str, Any]]]] = {
    "dowser": {},
    "brepphylo": {},
    "clonaltree": {
        "csv": [
            {
                "step": "convert_csv_to_tsv",
                "from": "csv",
                "to": "tsv",
                "requires": [],
            }
        ]
    },
    "gctree": {
        "csv": [
            {
                "step": "convert_table_to_aligned_fasta",
                "from": "csv",
                "to": "fasta",
                "requires": ["aligned_seq_column"],
            }
        ],
        "tsv": [
            {
                "step": "convert_table_to_aligned_fasta",
                "from": "tsv",
                "to": "fasta",
                "requires": ["aligned_seq_column"],
            }
        ],
    },
}

EXTENSION_ALIASES: dict[str, str] = {
    "fas": "fasta",
    "fsa": "fasta",
    "rdata": "rda",
}


def normalize_extension(value: str) -> str:
    raw = value.strip().lower()
    if not raw:
        return ""
    cleaned = raw.rsplit(".", 1)[-1]
    return EXTENSION_ALIASES.get(cleaned, cleaned)


def extension_from_path(path: Path) -> str:
    return normalize_extension(path.suffix.lstrip("."))


def native_accepts(method_id: MethodId) -> set[str]:
    return set(NATIVE_ACCEPTS_BY_METHOD[method_id])


def is_native_accept(method_id: MethodId, input_ext: str) -> bool:
    return normalize_extension(input_ext) in NATIVE_ACCEPTS_BY_METHOD[method_id]


def safe_conversion_chain(method_id: MethodId, input_ext: str) -> list[dict[str, Any]]:
    ext = normalize_extension(input_ext)
    raw = SAFE_CONVERSION_PATHS.get(method_id, {}).get(ext, [])
    return copy.deepcopy(raw)


def describe_safe_paths(method_id: MethodId) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for from_ext, chain in SAFE_CONVERSION_PATHS.get(method_id, {}).items():
        if not chain:
            continue
        terminal = chain[-1].get("to", from_ext)
        requires: list[str] = []
        for step in chain:
            requires.extend(step.get("requires", []))
        result.append(
            {
                "from": from_ext,
                "to": terminal,
                "steps": [step.get("step") for step in chain],
                "requires": sorted(set(requires)),
            }
        )
    return result
