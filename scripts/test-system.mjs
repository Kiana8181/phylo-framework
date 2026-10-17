/**
 * System tests: the real stack under pressure (tests/system).
 *
 *   npm run test:system                 start the stack, run every scenario, remove the stack
 *   npm run test:system -- --build      rebuild the images first
 *   npm run test:system -- --keep-services
 *   npm run test:system -- -k memory    extra arguments go to pytest
 *
 * Owns only the isolated `phylo-tests` compose project (the same one the other
 * test commands use, so do not run them at the same time). The tests stop,
 * kill and reconfigure containers of that project and nothing else. They need
 * Docker Compose 2.24 or newer and are meant for a development machine or CI,
 * never for a server that runs the application.
 */
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(root);
const python = process.env.TEST_PYTHON || (fs.existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python');
const args = process.argv.slice(2);
const keep = args.includes('--keep-services');
const build = args.includes('--build');
const pytestArgs = args.filter(a => a !== '--keep-services' && a !== '--build');
const compose = ['compose', '-f', 'docker-compose.test.yml', '-f', 'tests/system/docker-compose.system.yml', '--profile', 'full'];
function run(cmd, cmdArgs) {
  console.log(`\n> ${cmd} ${cmdArgs.join(' ')}`);
  const result = spawnSync(cmd, cmdArgs, {stdio: 'inherit'});
  if (result.error || result.status !== 0) throw new Error(`${cmd} failed (${result.status}): ${result.error?.message || cmdArgs.join(' ')}`);
}
let failed = false;
try {
  fs.mkdirSync('coverage/system', {recursive: true});
  // A stack left over from another test command has other settings: start clean.
  spawnSync('docker', [...compose, 'down', '-v'], {stdio: 'inherit'});
  if (build) run('docker', [...compose, 'build', 'api', 'gctree', 'clonaltree', 'dowser', 'brepphylo']);
  run('docker', [...compose, 'up', '-d', '--wait', 'postgres', 'minio']);
  run(python, ['scripts/init-test-services.py']);
  run('docker', [...compose, 'up', '-d', '--wait']);
  run(python, ['scripts/wait-test-methods.py']);
  run(python, ['-m', 'pytest', '-c', 'pytest.ini', 'tests/system', '-m', 'system', '-q', '-p', 'no:cacheprovider',
    '--junitxml=coverage/system/junit.xml', ...pytestArgs]);
} catch (error) {
  failed = true;
  console.error(error.message);
} finally {
  const logs = spawnSync('docker', [...compose, 'logs', '--no-color'], {encoding: 'utf8', maxBuffer: 200 * 1024 * 1024});
  fs.mkdirSync('coverage/system', {recursive: true});
  fs.writeFileSync('coverage/system/docker.log', (logs.stdout || '') + (logs.stderr || ''));
  if (!keep) {
    const cleanup = spawnSync('docker', [...compose, 'down', '-v'], {stdio: 'inherit'});
    if (cleanup.status !== 0) failed = true;
  }
}
process.exitCode = failed ? 1 : 0;
