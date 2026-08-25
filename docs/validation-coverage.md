# Input validation coverage across methods

Each method validates its input **in-service**, before the underlying algorithm runs.
This matrix records what each method checks, so gaps are a deliberate decision rather than an
accident of code paths. It complements the framework-level structural checks in
`apps/api/preprocess/` (delimiter/BOM normalization, row-width, blank-row dropping).

## Framework-level structural validation

`apps/api/preprocess/validate_input.py` runs in the orchestrator **before dispatch to any
method service**. It carries only checks that are invalid for *every* method regardless of
configuration, so it holds no method-specific branches:

1. completely empty file
2. header-only file (no data rows)
3. required identifier and sequence columns present
4. empty `sequence_id`
5. empty sequence
6. characters that are not nucleotides or gaps

All six are hard errors, and all four methods produce the same error code and the same message
for each. The stage inspects rather than transforms, so it logs
(`preprocess.validate_input_table`) but does not join the conversion chain.

**Checks whose answer depends on the method stay with the method.** Two in particular:

| Check | Where it is enforced |
|---|---|
| **Alignment-length equality** | Dowser `validators.R`; GCtree table→FASTA adapter; ClonalTree `validators.py` (fatal only when `use_input_alignment`); brepphylo `validate_aligned_imgt_gapped` (fatal only in `aligned_imgt_gapped` mode) |
| **Identifier uniqueness** | Dowser `validate_sequence_id_uniqueness`; GCtree `validate_fasta_record_ids` + FASTA adapter; ClonalTree `validators.py` (global); brepphylo `precheck_label_uniqueness` (per clone) |

One transforming step also validates, because it is the only place that can: when GCtree's
tabular adapter is told the table has no germline row, `insert_root_row`
(`apps/api/preprocess/converters.py`) rejects a germline sequence whose length differs from the
table's modal alignment length (`ROOT_SEQUENCE_LENGTH_MISMATCH`) and an ID already used by a row
(`ROOT_ID_ALREADY_PRESENT`). Both are hard errors, raised before the structural stage so the
message names the sequence the user pasted rather than a row number they did not write. The row
is inserted *before* `validate_input_table`, so it then goes through checks 4–6 above like any
other row.

Both ClonalTree and brepphylo re-align by default — MUSCLE and Clustal respectively — so ragged
input is legitimate for them and a blanket framework-level hard-fail would reject valid data.

## Coverage matrix

| Concern | Dowser | GCtree | brepphylo | ClonalTree |
|---|---|---|---|---|
| **File readable / non-empty / has header** | ✅ | ✅ | ✅ | ✅ (new) |
| **Required columns present** | ✅ `validate_required_columns` | ✅ (tabular adapter) | ✅ `plumber.R` col check | ✅ (new, hard-fail) |
| **AIRR format / extension** | ✅ `validate_fast_extension` | ✅ FASTA DNA-char check | ✅ ext + IMGT-gap mode | ⚠️ light header check (warn) |
| **Incomplete / empty rows** | ✅ `validate_alignment_presence`, `validate_clone_consistency` | ✅ empty record check | ✅ `validate_required_rows` | ⚠️ warn + count (rows dropped downstream) |
| **Duplicate IDs** | ✅ `validate_sequence_id_uniqueness` (fatal) | ✅ `validate_fasta_record_ids` (fatal) | ✅ per-clone label uniqueness `precheck_label_uniqueness` | ✅ (new, fatal on duplicate `sequence_id`) |
| **Inconsistencies (length / clone / trait)** | ✅ length, junction, clone, isotype, DTA trait | ✅ alignment-length equality | ✅ mixed-germline, clone-ID safety, **alignment-length equality in `aligned_imgt_gapped` mode** | ✅ **alignment-length equality when `use_input_alignment`**; ⚠️ warn otherwise (MUSCLE re-aligns) |

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
  ClonalTree's validator now **hard-fails on unequal alignment lengths when
  `use_input_alignment` is set**, because the alignment is then consumed as given; without the
  flag it remains a warning, as MUSCLE re-aligns.
- **brepphylo duplicate `sequence_id`.** *Not added globally.* brepphylo builds per-clone trees
  and already enforces the meaningful constraint — label uniqueness **within each clone**
  (`precheck_label_uniqueness`, `validators.R:402`) — and generates unique tip IDs when no ID
  column exists (`validators.R:394`). A global `sequence_id` duplicate check would be redundant,
  or worse, reject legitimate inputs where an ID repeats across *different* clones.
  Uniqueness is therefore left to brepphylo entirely; the orchestrator does not check it.
- **GCtree / Dowser.** No gaps identified; validation is already comprehensive for their
  respective input contracts (aligned FASTA and AIRR/Change-O clone tables).
