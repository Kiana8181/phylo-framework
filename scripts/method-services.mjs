#!/usr/bin/env node
/**
 * Central control for method services (dowser, gctree, brepphylo, clonaltree).
 * Usage:
 *   node scripts/method-services.mjs sync-env   # Write METHOD_*_URL to apps/api/.env
 *   node scripts/method-services.mjs list       # List services and URLs
 *   node scripts/method-services.mjs start     # Start all via Docker
 *   node scripts/method-services.mjs start gctree dowser  # Start only these
 *   node scripts/method-services.mjs stop      # Stop all
 *   node scripts/method-services.mjs stop gctree
 */

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import process from "node:process";

const ROOT = path.resolve(process.cwd());
const CONFIG_PATH = path.join(ROOT, "config", "method-services.json");
const API_ENV_PATH = path.join(ROOT, "apps", "api", ".env");
const CONTRACTS_DIR_REL = "packages/contracts";

function loadConfig() {
  const raw = fs.readFileSync(CONFIG_PATH, "utf8");
  const config = JSON.parse(raw);
  if (!Array.isArray(config.services)) throw new Error("config/method-services.json must have 'services' array");
  return config;
}

function getMethodUrl(config, service) {
  const host = config.host ?? "localhost";
  return `http://${host}:${service.port}`;
}

// --- sync-env ---
function syncEnv() {
  const config = loadConfig();
  const host = config.host ?? "localhost";
  let envContent = "";
  const envPath = API_ENV_PATH;
  if (fs.existsSync(envPath)) {
    envContent = fs.readFileSync(envPath, "utf8");
  }
  const lines = envContent.split(/\r?\n/);
  const methodKeyPrefix = "METHOD_";
  const methodKeySuffix = "_URL";
  const newMethodVars = new Map();
  for (const s of config.services) {
    const key = `METHOD_${s.id.toUpperCase()}_URL`;
    newMethodVars.set(key, getMethodUrl(config, s));
  }
  const serviceFilePrefixKey = "METHOD_SERVICE_FILE_PREFIX";
  const hasServiceFilePrefix = lines.some((l) => new RegExp(`^\\s*${serviceFilePrefixKey}\\s*=`).test(l));
  if (!hasServiceFilePrefix) {
    newMethodVars.set(serviceFilePrefixKey, "/runtime/storage");
  }
  const kept = lines.filter((line) => {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) return true;
    const eq = trimmed.indexOf("=");
    if (eq === -1) return true;
    const key = trimmed.slice(0, eq).trim();
    if (key.startsWith(methodKeyPrefix) && key.endsWith(methodKeySuffix)) return false;
    if (key === serviceFilePrefixKey) return false;
    return true;
  });
  const methodLines = [...newMethodVars.entries()].map(([k, v]) => `${k}=${v}`);
  const hasContracts = kept.some((l) => /^\s*CONTRACTS_DIR\s*=/.test(l));
  const insert = [];
  if (!hasContracts) insert.push(`CONTRACTS_DIR=${CONTRACTS_DIR_REL}`);
  const hasCors = kept.some((l) => /^\s*CORS_ORIGINS\s*=/.test(l));
  if (!hasCors) insert.push("CORS_ORIGINS=http://localhost:3000");
  const out = [...kept, ...(insert.length ? ["", "# Method services (from config/method-services.json)"] : []), ...insert, ...methodLines].join("\n");
  fs.writeFileSync(envPath, out.endsWith("\n") ? out : out + "\n", "utf8");
  console.log("Updated", path.relative(ROOT, envPath));
  for (const [k, v] of newMethodVars) console.log(" ", k, "=", v);
}

// --- list ---
function list() {
  const config = loadConfig();
  console.log("\nMethod services (from config/method-services.json):\n");
  const idLen = Math.max(4, ...config.services.map((s) => s.id.length));
  const urlLen = Math.max(3, ...config.services.map((s) => getMethodUrl(config, s).length));
  console.log("  " + "id".padEnd(idLen) + "  port   URL");
  console.log("  " + "-".repeat(idLen) + "  ----   " + "-".repeat(urlLen));
  for (const s of config.services) {
    console.log("  " + s.id.padEnd(idLen) + "  " + String(s.port).padStart(4) + "   " + getMethodUrl(config, s));
  }
  console.log("");
}

// --- docker helpers ---
function dockerBuild(serviceDir, image) {
  return new Promise((resolve, reject) => {
    const cwd = path.isAbsolute(serviceDir) ? serviceDir : path.join(ROOT, serviceDir);
    const proc = spawn("docker", ["build", "-t", image, "."], { stdio: "inherit", cwd, shell: process.platform === "win32" });
    proc.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`docker build exited ${code}`))));
  });
}

function containerName(id) {
  return `phylo-method-${id}`;
}

const STORAGE_DIR_REL = "runtime/storage";

function dockerRun(config, service) {
  const contractsPath = path.join(ROOT, CONTRACTS_DIR_REL.replace(/\//g, path.sep));
  const storagePath = path.join(ROOT, STORAGE_DIR_REL.replace(/\//g, path.sep));
  const name = containerName(service.id);
  const args = [
    "run",
    "--rm",
    "-d",
    "--name", name,
    "-p", `${service.port}:${service.port}`,
    "-v", `${contractsPath}:/contracts:ro`,
    "-e", "CONTRACTS_DIR=/contracts",
    "-v", `${storagePath}:/runtime/storage:ro`,
    "-e", "RUNS_DIR=/runtime/storage",
    service.dockerImage,
  ];
  return new Promise((resolve, reject) => {
    const proc = spawn("docker", args, { stdio: "inherit", shell: process.platform === "win32" });
    proc.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`docker run exited ${code}`))));
  });
}

function dockerStop(id) {
  const name = containerName(id);
  return new Promise((resolve, reject) => {
    const proc = spawn("docker", ["stop", name], { stdio: "inherit", shell: process.platform === "win32" });
    proc.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`docker stop exited ${code}`));
    });
  });
}

// --- start ---
async function start(serviceIds) {
  const config = loadConfig();
  const toStart = serviceIds.length
    ? config.services.filter((s) => serviceIds.includes(s.id.toLowerCase()))
    : config.services;
  if (toStart.length === 0) {
    console.log("No matching services. Available:", config.services.map((s) => s.id).join(", "));
    process.exit(1);
  }
  const storageDir = path.join(ROOT, STORAGE_DIR_REL.replace(/\//g, path.sep));
  if (!fs.existsSync(storageDir)) {
    fs.mkdirSync(storageDir, { recursive: true });
    console.log("Created", path.relative(ROOT, storageDir), "(method services read uploads from here)");
  }
  for (const s of toStart) {
    const servicePath = s.path || `services/${s.id}`;
    const image = s.dockerImage || `phylo-${s.id}:dev`;
    const absPath = path.join(ROOT, servicePath.replace(/\//g, path.sep));
    console.log("\nBuilding", s.id, "...");
    await dockerBuild(absPath, image);
    console.log("Starting", s.id, "on port", s.port, "...");
    await dockerRun(config, s);
  }
  console.log("\nStarted:", toStart.map((s) => `${s.id} → http://${config.host ?? "localhost"}:${s.port}`).join(", "));
  console.log("Run 'npm run services:sync-env' if you changed ports, then restart the API.");
}

// --- stop ---
async function stop(serviceIds) {
  const config = loadConfig();
  const toStop = serviceIds.length
    ? config.services.filter((s) => serviceIds.includes(s.id.toLowerCase()))
    : config.services;
  for (const s of toStop) {
    try {
      await dockerStop(s.id);
      console.log("Stopped", s.id);
    } catch (e) {
      if (e.message.includes("exited") && !e.message.includes("0")) {
        const name = containerName(s.id);
        console.warn("Container", name, "may not be running:", e.message);
      } else throw e;
    }
  }
}

// --- main ---
const [,, cmd, ...rest] = process.argv;
const sub = (cmd || "").toLowerCase();

if (sub === "sync-env" || sub === "sync") {
  syncEnv();
} else if (sub === "list") {
  list();
} else if (sub === "start") {
  start(rest).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
} else if (sub === "stop") {
  stop(rest).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
} else {
  console.log(`
Method services — central control (config: config/method-services.json)

  npm run services:sync-env     Write METHOD_*_URL into apps/api/.env
  npm run services:list         List services and ports
  npm run services:start        Start all method services (Docker)
  npm run services:start -- gctree dowser   Start only these
  npm run services:stop         Stop all
  npm run services:stop -- gctree          Stop one

Edit config/method-services.json to change ports or add services, then run sync-env.
`);
  process.exit(sub ? 1 : 0);
}
