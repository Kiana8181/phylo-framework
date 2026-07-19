# Sample datasets

`phylo-runner-sample.tsv` is an **empty template**. Its header row is the union
of every column the four methods require between them (in canonical AIRR names),
so a file with these columns — filled with your data — runs through Dowser,
GCtree, BrepPhylo and ClonalTree with their default settings.

The header set is derived from the single source of truth,
`packages/contracts/methods/<method>/columns.json` (the same files the API
upload validator and the Data requirements docs page read). It includes each
method's always-required columns plus ClonalTree's refinement columns (its
refinement step is on by default). Conditional-only columns that are off by
default — Dowser paired-chain (`cell_id`, `locus`) and region columns, isotype
`c_call` — are intentionally omitted; add them only if you enable those options.

BrepPhylo names its input columns via `*_column` params rather than an AIRR
`column_map`; point those params at the canonical columns here
(`sequence_column → sequence_alignment`, `clone_id_column → clone_id`,
`germline_id_column → germline_alignment_d_mask`).

## TODO (author) — before release

The committed file has the header row and blank rows only. Optionally replace the
blank rows with a small, **de-identified** example dataset (a few filled rows)
cleared for public distribution. No code change is needed when you swap the
contents — the download button references this same file.
