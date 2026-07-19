// Authoring-time only. Renders each diagrams/*.dot spec to a static SVG in
// apps/web/public/docs/ using @hpcc-js/wasm (Graphviz compiled to WebAssembly —
// deterministic layout, no `dot` binary required). This script is NEVER imported
// by the Next.js app. Re-run after editing a .dot file:
//   cd scripts/generate-docs-diagrams && npm install && node generate.mjs
import { readFileSync, writeFileSync, readdirSync, mkdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { Graphviz } from "@hpcc-js/wasm/graphviz";

const here = dirname(fileURLToPath(import.meta.url));
const dotDir = join(here, "diagrams");
const outDir = resolve(here, "../../apps/web/public/docs");
mkdirSync(outDir, { recursive: true });

const graphviz = await Graphviz.load();

const dotFiles = readdirSync(dotDir).filter((f) => f.endsWith(".dot"));
for (const file of dotFiles) {
  const src = readFileSync(join(dotDir, file), "utf8");
  const svg = graphviz.dot(src, "svg");
  const outPath = join(outDir, file.replace(/\.dot$/, ".svg"));
  writeFileSync(outPath, svg);
  console.log(`wrote ${outPath} (${svg.length} bytes)`);
}
console.log(`done — ${dotFiles.length} diagram(s)`);
