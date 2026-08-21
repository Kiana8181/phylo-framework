#!/usr/bin/env node
// Build/deploy-time capture of the environment identity behind a deployment.
//
// Writes `runtime/version-info.json`, which the worker copies into every run's
// stored result under `version_info`. Run it from the repo root as part of a
// build or deploy; there is no manual editing step.
//
//   node scripts/generate-version-info.mjs [--out <path>]
//
// A field that cannot be determined here is written as `null` and its reason is
// recorded in `unavailable`, so a reader can tell "not captured" apart from
// "captured as empty". Nothing in this file invents a version string.

import { execFileSync } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/** Run a command, returning trimmed stdout or null if it fails for any reason. */
function tryExec(file, args, cwd = ROOT) {
  try {
    return execFileSync(file, args, { cwd, encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim() || null;
  } catch {
    return null;
  }
}

function readTextIfPresent(path) {
  try {
    return readFileSync(path, "utf8");
  } catch {
    return null;
  }
}

function readJsonIfPresent(path) {
  const raw = readTextIfPresent(path);
  if (raw == null) return null;
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

const unavailable = {};
function markUnavailable(field, reason) {
  unavailable[field] = reason;
  return null;
}

// ---------------------------------------------------------------- framework

const isGitRepo = existsSync(join(ROOT, ".git"));

const gitCommit = isGitRepo
  ? tryExec("git", ["rev-parse", "HEAD"])
  : markUnavailable("framework.git_commit", "not a git checkout at build time");

const gitDescribe = isGitRepo ? tryExec("git", ["describe", "--tags", "--always", "--dirty"]) : null;
const gitBranch = isGitRepo ? tryExec("git", ["rev-parse", "--abbrev-ref", "HEAD"]) : null;
const gitStatus = isGitRepo ? tryExec("git", ["status", "--porcelain"]) : null;

const framework = {
  // `git describe` is the closest thing to a release identity this repo has;
  // package.json carries no version field.
  version: gitDescribe ?? markUnavailable("framework.version", "git describe unavailable"),
  git_commit: gitCommit,
  git_branch: gitBranch,
  // null (rather than false) when we could not determine cleanliness at all.
  git_dirty: gitStatus == null ? null : gitStatus.length > 0,
};

// ----------------------------------------------------------------- services

/** Pull `ARG NAME=value` pairs out of a Dockerfile. */
function dockerfileArgs(text) {
  const out = {};
  for (const line of text.split("\n")) {
    const m = /^\s*ARG\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+?)\s*$/.exec(line);
    if (m) out[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
  return out;
}

/** First `FROM <image>` in a Dockerfile, ignoring the `AS stage` suffix. */
function dockerfileBaseImage(text) {
  const m = /^\s*FROM\s+(\S+)/m.exec(text);
  return m ? m[1] : null;
}

/** Parse pinned `pkg==version` lines from a pip requirements file. */
function requirementPins(text) {
  const out = {};
  for (const line of text.split("\n")) {
    const m = /^\s*([A-Za-z0-9._-]+)(?:\[[^\]]*\])?\s*==\s*([^\s#]+)/.exec(line);
    if (m) out[m[1]] = m[2];
  }
  return out;
}

// Only tools the thesis actually names are surfaced per service; the rest of a
// requirements file is build noise.
const TOOLS_OF_INTEREST = new Set(["gctree", "ete3", "numpy", "scipy", "biopython", "muscle"]);

const serviceConfig = readJsonIfPresent(join(ROOT, "config", "method-services.json"));
const serviceEntries = serviceConfig?.services ?? [];
if (!serviceEntries.length) {
  markUnavailable("services", "config/method-services.json missing or has no services");
}

const services = {};
for (const entry of serviceEntries) {
  const id = entry.id;
  const servicePath = join(ROOT, entry.path ?? join("services", id));
  const dockerfile = readTextIfPresent(join(servicePath, "Dockerfile"));

  const record = {
    image_name: entry.dockerImage ?? null,
    // The digest only exists once an image has been built and tagged by a
    // registry; a local `:dev` build has none. Resolved below when possible.
    image_digest: null,
    base_image: null,
    build_args: {},
    tool_versions: {},
  };

  if (dockerfile == null) {
    unavailable[`services.${id}.base_image`] = "Dockerfile not readable at build time";
  } else {
    record.base_image = dockerfileBaseImage(dockerfile);
    record.build_args = dockerfileArgs(dockerfile);
  }

  // Pinned Python tool versions, where the service uses pip.
  for (const name of ["requirements.docker.txt", "requirements.txt"]) {
    const reqs = readTextIfPresent(join(servicePath, name));
    if (reqs == null) continue;
    for (const [pkg, version] of Object.entries(requirementPins(reqs))) {
      if (TOOLS_OF_INTEREST.has(pkg.toLowerCase())) record.tool_versions[pkg] = version;
    }
  }

  // Ask the local Docker daemon for the built image's digest. Absent in a dev
  // deployment that never pushed the image — recorded as unavailable, not faked.
  if (record.image_name) {
    const digest = tryExec("docker", [
      "image",
      "inspect",
      record.image_name,
      "--format",
      "{{index .RepoDigests 0}}",
    ]);
    if (digest) {
      record.image_digest = digest;
    } else {
      unavailable[`services.${id}.image_digest`] =
        "image not present locally, or built without a registry digest";
    }
  }

  if (!Object.keys(record.tool_versions).length) {
    unavailable[`services.${id}.tool_versions`] =
      "no pinned versions found in the build definition; the service reports its own at run time";
  }

  services[id] = record;
}

// Reference data (germline databases and similar) is baked into the upstream
// images rather than pinned by this repository.
const referenceData = markUnavailable(
  "reference_data",
  "reference germline data is bundled inside the upstream tool images and carries no separate version in this deployment",
);

// ------------------------------------------------------------------- output

const payload = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  framework,
  services,
  reference_data: referenceData,
  unavailable,
};

const outFlag = process.argv.indexOf("--out");
const outPath = outFlag !== -1 && process.argv[outFlag + 1]
  ? resolve(process.argv[outFlag + 1])
  : join(ROOT, "runtime", "version-info.json");

mkdirSync(dirname(outPath), { recursive: true });
writeFileSync(outPath, `${JSON.stringify(payload, null, 2)}\n`, "utf8");

const unavailableCount = Object.keys(unavailable).length;
console.log(
  `version-info written to ${outPath} ` +
    `(framework ${framework.version ?? "unknown"}, ` +
    `${Object.keys(services).length} services, ${unavailableCount} field(s) unavailable)`,
);
