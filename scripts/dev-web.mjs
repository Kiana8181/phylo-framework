#!/usr/bin/env node

import { spawn } from "node:child_process";
import process from "node:process";

const npmCmd = process.platform === "win32" ? "npm.cmd" : "npm";
const forwardedArgs = process.argv.slice(2);
const args = ["-w", "web", "run", "dev"];

if (forwardedArgs.length > 0) {
  args.push("--", ...forwardedArgs);
}

const spawnOpts = {
  stdio: "inherit",
  env: process.env,
};
// On Windows, spawning .cmd files requires shell (Node security patch CVE-2024-27980)
if (process.platform === "win32") {
  spawnOpts.shell = true;
}
const child = spawn(npmCmd, args, spawnOpts);

const forwardSignal = (signal) => {
  if (!child.killed) child.kill(signal);
};

process.on("SIGINT", () => forwardSignal("SIGINT"));
process.on("SIGTERM", () => forwardSignal("SIGTERM"));

child.on("error", (error) => {
  console.error(`Failed to start web dev server: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 1);
});
