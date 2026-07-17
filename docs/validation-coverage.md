# Input validation coverage across methods

Each method validates its input **in-service**, before the underlying algorithm runs.
This matrix records what each method checks, so gaps are a deliberate decision rather than an
accident of code paths. It complements the framework-level structural checks in
`apps/api/preprocess/` (delimiter/BOM normalization, row-width, blank-row dropping).

## Coverage matrix

| Concern | Dowser | GCtree | brepphylo | ClonalTree |
|---|---|---|---|---|
| **File readable / non-empty / has header** | ✅ | ✅ | ✅ | ✅ (new) |
| **Required columns present** | ✅ `validate_required_columns` | ✅ (tabular adapter) | ✅ `plumber.R` col check | ✅ (new, hard-fail) |
| **AIRR format / extension** | ✅ `validate_fast_extension` | ✅ FASTA DNA-char check | ✅ ext + IMGT-gap mode | ⚠️ light header check (warn) |
| **Incomplete / empty rows** | ✅ `validate_alignment_presence`, `validate_clone_consistency` | ✅ empty record check | ✅ `validate_required_rows` | ⚠️ warn + count (rows dropped downstream) |
| **Duplicate IDs** | ✅ `validate_sequence_id_uniqueness` (fatal) | ✅ `validate_fasta_record_ids` (fatal) | ✅ per-clone label uniqueness `precheck_label_uniqueness` | ✅ (new, fatal on duplicate `sequence_id`) |
| **Inconsistencies (length / clone / trait)** | ✅ length, junction, clone, isotype, DTA trait | ✅ alignment-length equality | ✅ mixed-germline, clone-ID safety | ⚠️ alignment-length spread (warn; MUSCLE re-aligns) |

✅ = enforced (hard-fail where fatal)  ⚠️ = warning only (run proceeds)

## Reference locations

- **Dowser** — `services/dowser/validators.R`
- **GCtree** — `services/gctree/app.py` (`validate_fasta_for_gctree`, ~line 535)
- **brepphylo** — `services/brepphylo/validators.R`
- **ClonalTree** — `services/clonaltree/validators.py` (added; hooked in `app.py` before the
  format step)

## Audit decisions (why some cells are intentionally left as-is)

- **ClonalTree strictness.** Incomplete rows are silently dropped inside the base-codes
  submodule (`dropna`). To avoid breaking currently-working inputs, ClonalTree's new validator
  **warns** on incomplete rows and non-uniform alignment lengths instead of failing. It
  hard-fails only on unreadable input, missing required columns, and empty/duplicate
  `sequence_id`. The base-codes submodule is not modified.
- **brepphylo duplicate `sequence_id`.** *Not added.* brepphylo builds per-clone trees and
  already enforces the meaningful constraint — label uniqueness **within each clone**
  (`precheck_label_uniqueness`, `validators.R:402`) — and generates unique tip IDs when no ID
  column exists (`validators.R:394`). A global `sequence_id` duplicate check would be redundant,
  or worse, reject legitimate inputs where an ID repeats across *different* clones. Left as a
  documented note.
- **GCtree / Dowser.** No gaps identified; validation is already comprehensive for their
  respective input contracts (aligned FASTA and AIRR/Change-O clone tables).
