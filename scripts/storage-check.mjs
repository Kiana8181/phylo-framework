#!/usr/bin/env node

// Storage connectivity smoke test.
//
//   node --env-file=.env ./scripts/storage-check.mjs            # host venv (uses S3_ENDPOINT_URL)
//   node --env-file=.env ./scripts/storage-check.mjs --docker   # run inside the api container
//
// The host form requires the MinIO API port to be published (compose maps
// ${MINIO_API_PORT:-9000}). The --docker form uses the in-cluster endpoint.

import { spawn } from "node:child_process";
import process from "node:process";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const useDocker = process.argv.includes("--docker");

let cmd;
let args;
let opts = { stdio: "inherit", env: process.env, cwd: ROOT };

if (useDocker) {
  cmd = "docker";
  args = ["compose", "exec", "-T", "api", "python", "-m", "apps.api.scripts.storage_check"];
} else {
  const isWin = process.platform === "win32";
  const venvDir = path.join(ROOT, ".venv", isWin ? "Scripts" : "bin");
  const pythonBin = path.join(venvDir, isWin ? "python.exe" : "python");
  if (!fs.existsSync(pythonBin)) {
    console.error("ERROR: Missing .venv. Create/install the API venv first, or pass --docker.");
    process.exit(1);
  }
  cmd = pythonBin;
  args = ["-m", "apps.api.scripts.storage_check"];
  if (isWin) opts.shell = true;
}

const child = spawn(cmd, args, opts);
child.on("error", (err) => {
  console.error(`Failed to run storage check: ${err.message}`);
  process.exit(1);
});
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
