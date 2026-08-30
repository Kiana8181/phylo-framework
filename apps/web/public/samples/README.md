# Sample dataset

`ExampleAirr_clone_3128.tsv` is **clone 3128 of the official Dowser example
dataset** (`ExampleAirr`), extracted as a standalone AIRR rearrangement table:
43 sequences, one clone, canonical AIRR column names.

It is the file the Data requirements and Try it yourself docs pages hand out, and
the one the "Try it yourself" button uploads on the reader's behalf.

## Why only one clone

GCtree accepts **one clone per run** — that is a limitation of GCtree itself, not
of this framework. Restricting the file to a single clone is what lets the *same*
file be pushed through all four methods, so their trees can be compared side by
side. For Dowser, BrepPhylo and ClonalTree a multi-clone dataset is perfectly
fine, as long as it carries the columns that method needs.

## Provenance

Produced by the reproducibility harness in `article-tests/`. The copies here are
verbatim:

| File | Source (`article-tests/tests-results/ExampleAirr_clone_3128/`) |
|---|---|
| `ExampleAirr_clone_3128.tsv` | `ExampleAirr_clone_3128.tsv` |
| `trees/dowser.png` | `dowser/Run 1/tree.png` |
| `trees/gctree.png` | `gctree/Run 1/tree.png` |
| `trees/brepphylo.png` | `brepphylo/Run 1/tree.png` |
| `trees/clonaltree.png` | `clonaltree/Run 1/tree.png` |

The parameters that produced each tree live in the matching `Run 1/inputs.json`
and are transcribed into `apps/web/features/docs/sample.ts`. Runs 1–3 of each
method use identical parameters, so Run 1 is the canonical one. If the harness is
re-run and the outputs change, re-copy the PNGs and update `sample.ts` together.
