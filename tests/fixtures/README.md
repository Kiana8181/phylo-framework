# Scientific regression fixture

`scientific-params.json` records the four parameter sets in
`apps/web/features/docs/sample.ts`. The scientific tests use the existing
`apps/web/public/samples/ExampleAirr_clone_3128.tsv` (43 observed sequences from
Dowser's official ExampleAirr clone 3128; see that directory's README for provenance).

These are scientific smoke/regression scenarios, not a benchmark or proof of
biological accuracy. Assertions cover valid tree structure, API contracts, retained
outputs, byte counts, SHA-256 checksums, and history preservation. Do not compare
incidental ordering of stochastic trees or claim exact topology reproducibility
across dependency/platform changes without a separate reference analysis.
