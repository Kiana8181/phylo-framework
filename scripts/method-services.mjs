#!/usr/bin/env node
/**
 * Central control for method services (dowser, gctree, brepphylo, clonaltree).
 * Usage:
 *   node scripts/method-services.mjs sync-env
 *   node scripts/method-services.mjs list
 *   node scripts/method-services.mjs start [serviceIds...]
 *   node scripts/method-services.mjs stop [serviceIds...]
 */

import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
import process from "node:process";
import { fileURLToPath } from "node:url";

const SCRIPT_DIR = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(SCRIPT_DIR, "..");
const CONFIG_PATH = path.join(ROOT, "config", "method-services.json");
const ROOT_ENV_PATH = path.join(ROOT, ".env");
const LEGACY_API_ENV_PATH = path.join(ROOT, "apps", "api", ".env");

function loadConfig() {
  const raw = fs.readFileSync(CONFIG_PATH, "utf8");
  const config = JSON.parse(raw);
  if (!Array.isArray(config.services)) {
    throw new Error("config/method-services.json must have a 'services' array");
  }
  return config;
}

function stripWrappingQuotes(v) {
  const trimmed = v.trim();
  if ((trimmed.startsWith('"') && trimmed.endsWith('"')) || (trimmed.startsWith("'") && trimmed.endsWith("'"))) {
    return trimmed.slice(1, -1);
  }
  return trimmed;
}

function parseEnvContent(raw) {
  const out = new Map();
  for (const line of raw.split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const eq = trimmed.indexOf("=");
    if (eq === -1) continue;
    const key = trimmed.slice(0, eq).trim();
    const value = stripWrappingQuotes(trimmed.slice(eq + 1));
    if (key) out.set(key, value);
  }
  return out;
}

function loadEnvMap() {
  if (fs.existsSync(ROOT_ENV_PATH)) {
    return parseEnvContent(fs.readFileSync(ROOT_ENV_PATH, "utf8"));
  }
  if (fs.existsSync(LEGACY_API_ENV_PATH)) {
    return parseEnvContent(fs.readFileSync(LEGACY_API_ENV_PATH, "utf8"));
  }
  return new Map();
}

function resolveFromRoot(rawPath, fallbackRel) {
  const value = (rawPath || fallbackRel).trim();
  return path.isAbsolute(value) ? value : path.resolve(ROOT, value);
}

function serviceHostPort(service) {
  return Number(service.port);
}

function serviceContainerPort(service) {
  const raw = service.containerPort ?? service.port;
  return Number(raw);
}

function serviceDockerHost(service) {
  return service.composeHost || service.id;
}

function localMethodUrl(config, service) {
  const host = config.host || "localhost";
  return `http://${host}:${serviceHostPort(service)}`;
}

function dockerMethodUrl(service) {
  return `http://${serviceDockerHost(service)}:${serviceContainerPort(service)}`;
}

function updateEnvFileWithGeneratedVars(generatedVars) {
  let baseContent = "";
  if (fs.existsSync(ROOT_ENV_PATH)) {
    baseContent = fs.readFileSync(ROOT_ENV_PATH, "utf8");
  } else if (fs.existsSync(LEGACY_API_ENV_PATH)) {
    baseContent = fs.readFileSync(LEGACY_API_ENV_PATH, "utf8");
  }

  const lines = baseContent.split(/\r?\n/);
  const generatedKeyPattern = /^METHOD_[A-Z0-9_]+_(URL|URL_DOCKER|HOST_PORT|CONTAINER_PORT)$/;

  const kept = lines.filter((line) => {
    const trimmed = line.trim();
    if (trimmed === "# Method services (generated from config/method-services.json)") return false;
    if (!trimmed || trimmed.startsWith("#")) return true;
    const eq = trimmed.indexOf("=");
    if (eq === -1) return true;
    const key = trimmed.slice(0, eq).trim();
    return !generatedKeyPattern.test(key);
  });

  const keptContentMap = parseEnvContent(kept.join("\n"));
  const defaults = new Map([
    ["CONTRACTS_DIR", "packages/contracts"],
    ["CORS_ORIGINS", "http://localhost:3000"],
    ["NEXT_PUBLIC_API_BASE_URL", "http://localhost:8000"],
    ["STRICT_CONTRACT_ROUTES", "true"],
    ["STORAGE_LOCAL_PATH", "runtime/storage"],
    ["STORAGE_LOCAL_URL", "/storage"],
    ["HOST_RUNTIME_SHARED_ROOT", "/runtime/storage"],
    ["METHOD_SERVICE_FILE_PREFIX", "/runtime/storage"],
    ["POSTGRES_USER", "phylo_user"],
    ["POSTGRES_PASSWORD", "phylo_pass"],
    ["POSTGRES_DB", "phylo_db"],
    ["POSTGRES_HOST", "127.0.0.1"],
    ["POSTGRES_PORT", "5440"],
  ]);

  const insertDefaults = [];
  for (const [key, value] of defaults) {
    if (!keptContentMap.has(key)) {
      insertDefaults.push(`${key}=${value}`);
    }
  }

  const methodLines = [...generatedVars.entries()].map(([k, v]) => `${k}=${v}`);
  const outLines = [
    ...kept,
    ...(insertDefaults.length || methodLines.length ? [""] : []),
    ...(insertDefaults.length ? ["# Common defaults", ...insertDefaults, ""] : []),
    "# Method services (generated from config/method-services.json)",
    ...methodLines,
  ];

  const out = outLines.join("\n").replace(/\n{3,}/g, "\n\n");
  fs.writeFileSync(ROOT_ENV_PATH, out.endsWith("\n") ? out : `${out}\n`, "utf8");

  if (!fs.existsSync(ROOT_ENV_PATH) && fs.existsSync(LEGACY_API_ENV_PATH)) {
    console.warn("WARN: failed to create root .env; legacy apps/api/.env still exists.");
  }
}

function syncEnv() {
  const config = loadConfig();
  const generatedVars = new Map();

  for (const service of config.services) {
    const keyBase = `METHOD_${service.id.toUpperCase()}`;
    generatedVars.set(`${keyBase}_HOST_PORT`, String(serviceHostPort(service)));
    generatedVars.set(`${keyBase}_CONTAINER_PORT`, String(serviceContainerPort(service)));
    generatedVars.set(`${keyBase}_URL`, localMethodUrl(config, service));
    generatedVars.set(`${keyBase}_URL_DOCKER`, dockerMethodUrl(service));
  }

  updateEnvFileWithGeneratedVars(generatedVars);
  console.log("Updated", path.relative(ROOT, ROOT_ENV_PATH));
  for (const [k, v] of generatedVars.entries()) {
    console.log(" ", k, "=", v);
  }
}

function list() {
  const config = loadConfig();
  console.log("\nMethod services (from config/method-services.json):\n");
  const idLen = Math.max(4, ...config.services.map((s) => s.id.length));
  console.log(`  ${"id".padEnd(idLen)}  hostPort  containerPort  localURL                  dockerURL`);
  console.log(`  ${"-".repeat(idLen)}  --------  -------------  ------------------------  ------------------------`);
  for (const s of config.services) {
    const row = [
      s.id.padEnd(idLen),
      String(serviceHostPort(s)).padStart(8),
      String(serviceContainerPort(s)).padStart(13),
      localMethodUrl(config, s).padEnd(24),
      dockerMethodUrl(s),
    ];
    console.log("  " + row.join("  "));
  }
  console.log("");
}

function spawnWithPromise(cmd, args, opts = {}) {
  return new Promise((resolve, reject) => {
    const proc = spawn(cmd, args, {
      stdio: "inherit",
      shell: process.platform === "win32",
      ...opts,
    });
    proc.on("exit", (code) => {
      if (code === 0) resolve();
      else reject(new Error(`${cmd} ${args.join(" ")} exited ${code}`));
    });
  });
}

function containerName(id) {
  return `phylo-method-${id}`;
}

async function dockerBuild(service) {
  const servicePath = service.path || `services/${service.id}`;
  const absPath = resolveFromRoot(servicePath, `services/${service.id}`);
  const image = service.dockerImage || `phylo-${service.id}:dev`;
  await spawnWithPromise("docker", ["build", "-t", image, "."], { cwd: absPath });
}

async function removeIfExists(name) {
  try {
    await spawnWithPromise("docker", ["rm", "-f", name]);
  } catch {
    // ignore: container likely absent
  }
}

async function dockerRun(service, envMap) {
  const contractsPath = resolveFromRoot(envMap.get("CONTRACTS_DIR"), "packages/contracts");
  const storagePath = resolveFromRoot(envMap.get("STORAGE_LOCAL_PATH"), "runtime/storage");
  const containerStoragePath = (envMap.get("METHOD_SERVICE_FILE_PREFIX") || "/runtime/storage").trim();
  const containerMount = containerStoragePath.startsWith("/") ? containerStoragePath : "/runtime/storage";

  fs.mkdirSync(storagePath, { recursive: true });

  const name = containerName(service.id);
  const image = service.dockerImage || `phylo-${service.id}:dev`;
  const hostPort = serviceHostPort(service);
  const containerPort = serviceContainerPort(service);

  const args = [
    "run",
    "--rm",
    "-d",
    "--name",
    name,
    "--env-file",
    ROOT_ENV_PATH,
    "-p",
    `${hostPort}:${containerPort}`,
    "-v",
    `${contractsPath}:/contracts:ro`,
    "-v",
    `${storagePath}:${containerMount}:ro`,
    "-e",
    "CONTRACTS_DIR=/contracts",
    "-e",
    `RUNS_DIR=${containerMount}`,
    "-e",
    `METHOD_SERVICE_FILE_PREFIX=${containerMount}`,
    "-e",
    `STRICT_CONTRACT_ROUTES=${envMap.get("STRICT_CONTRACT_ROUTES") || "true"}`,
  ];

  const extraEnv = service.env && typeof service.env === "object" ? service.env : {};
  for (const [k, v] of Object.entries(extraEnv)) {
    args.push("-e", `${k}=${String(v)}`);
  }

  args.push(image);
  await spawnWithPromise("docker", args);
}

async function waitReady(baseUrl, timeoutSeconds = 120) {
  const probes = ["/spec", "/__docs__/"];
  const until = Date.now() + timeoutSeconds * 1000;

  while (Date.now() < until) {
    for (const p of probes) {
      try {
        const res = await fetch(`${baseUrl}${p}`);
        if (res.ok) return true;
      } catch {
        // ignore and retry
      }
    }
    await new Promise((r) => setTimeout(r, 1000));
  }
  return false;
}

async function printContainerLogs(id) {
  try {
    await spawnWithPromise("docker", ["logs", "--tail", "200", containerName(id)]);
  } catch {
    // ignore
  }
}

async function start(requestedIds) {
  syncEnv();

  const config = loadConfig();
  const wanted = new Set(requestedIds.map((s) => s.toLowerCase()));
  const toStart = wanted.size
    ? config.services.filter((s) => wanted.has(String(s.id).toLowerCase()))
    : config.services;

  if (!toStart.length) {
    console.log("No matching services. Available:", config.services.map((s) => s.id).join(", "));
    process.exit(1);
  }

  const envMap = loadEnvMap();
  const storagePath = resolveFromRoot(envMap.get("STORAGE_LOCAL_PATH"), "runtime/storage");
  fs.mkdirSync(storagePath, { recursive: true });

  for (const s of toStart) {
    console.log(`\nBuilding ${s.id} ...`);
    await dockerBuild(s);

    const name = containerName(s.id);
    await removeIfExists(name);

    console.log(`Starting ${s.id} on host port ${serviceHostPort(s)} ...`);
    await dockerRun(s, envMap);

    const ready = await waitReady(localMethodUrl(config, s));
    if (!ready) {
      console.error(`Readiness check failed for ${s.id} (${localMethodUrl(config, s)})`);
      await printContainerLogs(s.id);
      process.exit(1);
    }

    console.log(`Ready: ${s.id} -> ${localMethodUrl(config, s)}`);
  }

  console.log(`\nStarted: ${toStart.map((s) => `${s.id} -> ${localMethodUrl(config, s)}`).join(", ")}`);
}

async function stop(requestedIds) {
  const config = loadConfig();
  const wanted = new Set(requestedIds.map((s) => s.toLowerCase()));
  const toStop = wanted.size
    ? config.services.filter((s) => wanted.has(String(s.id).toLowerCase()))
    : config.services;

  for (const s of toStop) {
    const name = containerName(s.id);
    try {
      await spawnWithPromise("docker", ["stop", name]);
      console.log("Stopped", s.id);
    } catch (e) {
      console.warn(`Container ${name} may not be running: ${e.message}`);
    }
  }
}

function usage() {
  console.log(`
Method services - central control (config: config/method-services.json)

  npm run services:sync-env                    Write method vars into .env
  npm run services:list                        List services and URLs
  npm run services:start                       Build + start all method services
  npm run services:start -- gctree dowser      Build + start only these
  npm run services:stop                        Stop all method services
  npm run services:stop -- gctree              Stop one method service

Edit config/method-services.json, then run sync-env.
`);
}

const [, , cmdRaw, ...rest] = process.argv;
const cmd = (cmdRaw || "").toLowerCase();

if (cmd === "sync-env" || cmd === "sync") {
  syncEnv();
} else if (cmd === "list") {
  list();
} else if (cmd === "start") {
  start(rest).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
} else if (cmd === "stop") {
  stop(rest).catch((e) => {
    console.error(e.message);
    process.exit(1);
  });
} else {
  usage();
  process.exit(cmd ? 1 : 0);
}
