import inquirer from "inquirer";
import { spawn } from "node:child_process";
import process from "node:process";
import path from "node:path";

const ROOT = path.resolve(process.cwd());
const run = (cmd, args) =>
  new Promise((resolve, reject) => {
    const isSh = cmd.endsWith(".sh");
    const spawnCmd = isSh ? "bash" : cmd;
    const spawnArgs = isSh ? [cmd, ...(args || [])] : (args || []);
    const p = spawn(spawnCmd, spawnArgs, { stdio: "inherit", shell: false });
    p.on("exit", (code) => (code === 0 ? resolve() : reject(new Error(`${cmd} exited ${code}`))));
  });

const { mode } = await inquirer.prompt([
  {
    type: "list",
    name: "mode",
    message: "Choose how to run phylo-framework:",
    choices: [
      { name: "Dev — methods in Docker (recommended if R not installed)", value: "dev-docker" },
      { name: "Dev — methods in local R (fast if R deps are installed)", value: "dev-r" },
      { name: "Prod — docker compose (deployment)", value: "prod" },
    ],
  },
]);

if (mode === "dev-docker") {
  await run(path.join(ROOT, "scripts/dev-with-docker.sh"), []);
} else if (mode === "dev-r") {
  await run(path.join(ROOT, "scripts/dev-with-local-r.sh"), []);
} else {
  await run("docker", ["compose","--profile" ,"prod", "up", "-d", "--build"]);
}
