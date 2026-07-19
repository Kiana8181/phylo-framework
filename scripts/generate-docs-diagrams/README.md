# Docs diagram generator

Authoring-time only. Renders the in-app documentation diagrams
(`architecture`, `workflow`, `data-model`) from exact Graphviz specs to **static
SVG files** checked into `apps/web/public/docs/`. The SVGs are the artifact; the
Next.js app just `<img>`s them. This tool is **never** imported by `apps/web` and
is **not** listed in `apps/web/package.json`.

## What is installed

- **`@hpcc-js/wasm`** (pinned in this dir's `package.json`) — Graphviz compiled
  to WebAssembly. Same deterministic Graphviz layout engine as the `dot` CLI, but
  needs no system `dot` binary. Installed into this dir's own `node_modules`.

## Regenerate the diagrams

```bash
cd scripts/generate-docs-diagrams
npm install        # first time only — installs @hpcc-js/wasm here (isolated)
node generate.mjs  # renders diagrams/*.dot -> apps/web/public/docs/*.svg
```

## Editing a diagram

The source of truth for each diagram is its `diagrams/<name>.dot` spec. Edit the
`.dot`, re-run `node generate.mjs`, and commit both the `.dot` and the regenerated
`apps/web/public/docs/<name>.svg`.

Every box/edge must stay traceable to the real repo (services, ports, buckets,
routes in `README.md` / `docker-compose.yml` / `apps/api/…`; entities/columns in
`apps/api/database/models.py`). All specs render on a fixed white background so
the baked image reads correctly on the docs' fixed light card regardless of the
site's light/dark theme.
