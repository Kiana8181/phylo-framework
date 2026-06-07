#!/usr/bin/env node

import { spawn } from "node:child_process";
import process from "node:process";
import path from "node:path";
import fs from "node:fs";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const isWin = process.platform === "win32";
const venvDir = path.join(ROOT, ".venv", isWin ? "Scripts" : "bin");
const pythonName = isWin ? "python.exe" : "python";
const pythonBin = path.join(venvDir, pythonName);

if (!fs.existsSync(pythonBin)) {
  console.error("ERROR: Missing .venv. Create/install the API venv first (see README).");
  process.exit(1);
}

const python = pythonBin;
const rawStorage = process.env.STORAGE_LOCAL_PATH || "runtime/storage";
const hostStorage = path.isAbsolute(rawStorage) || /^[A-Za-z]:[\\/]/.test(rawStorage)
  ? rawStorage
  : path.join(ROOT, rawStorage);

if (!process.env.HOST_RUNTIME_SHARED_ROOT || process.env.HOST_RUNTIME_SHARED_ROOT.startsWith("/runtime/storage")) {
  process.env.HOST_RUNTIME_SHARED_ROOT = hostStorage;
}

fs.mkdirSync(hostStorage, { recursive: true });

const args = ["-m", "apps.api.workers.run_worker"];

const opts = { stdio: "inherit", env: process.env, cwd: ROOT };
if (isWin) opts.shell = true;

const child = spawn(python, args, opts);

const forward = (signal) => {
  if (!child.killed) child.kill(signal);
};
process.on("SIGINT", () => forward("SIGINT"));
process.on("SIGTERM", () => forward("SIGTERM"));

child.on("error", (err) => {
  console.error(`Failed to start run worker: ${err.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
