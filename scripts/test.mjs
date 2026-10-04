/** Reproducible local/CI test entrypoint. Owns only the phylo-tests project. */
import {spawnSync} from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
process.chdir(root);
const python = process.env.TEST_PYTHON || (fs.existsSync('.venv/bin/python') ? '.venv/bin/python' : 'python');
const full = process.argv.includes('--full');
const keep = process.argv.includes('--keep-services');
const baseCompose = ['compose', '-f', 'docker-compose.test.yml'];
const instrumented = [...baseCompose, '-f', 'docker-compose.coverage.yml', '--profile', 'full'];
function run(cmd, args, options = {}) {
  console.log(`\n> ${cmd} ${args.join(' ')}`);
  const result = spawnSync(cmd, args, {stdio: 'inherit', ...options});
  if (result.error || result.status !== 0) throw new Error(`${cmd} failed (${result.status}): ${result.error?.message || args.join(' ')}`);
}
let failed = false;
try {
  for (const dir of ['coverage', 'coverage/python', 'coverage/scientific']) fs.mkdirSync(dir, {recursive: true});
  // Fresh measurements; reports from previous runs must not inflate coverage.
  for (const dir of ['api-e2e', 'gctree-e2e', 'clonaltree-e2e', 'browser-raw'])
    fs.rmSync(path.join('coverage', dir), {recursive: true, force: true});
  run('docker', [...baseCompose, 'up', '-d', '--wait', 'postgres', 'minio']);
  run(python, ['scripts/init-test-services.py']);
  run('npm', ['-w', '@phylo/contracts', 'run', 'build']);
  run('npm', ['-w', '@phylo/contracts', 'run', 'test', '--', '--coverage']);
  run('npm', ['-w', 'web', 'run', 'test', '--', '--coverage']);
  run('npm', ['-w', 'web', 'exec', 'tsc', '--', '--noEmit']);
  run(python, ['-m', 'pytest', '-c', 'pytest.ini', '--cov', '--cov-report=xml', '--cov-report=html',
    '--cov-report=json:coverage/python/coverage.json', '--cov-report=term:skip-covered',
    '--junitxml=coverage/python/junit.xml', '-q']);
  run(python, ['scripts/check-coverage.py', '--fast']);
  if (full) {
    if (process.argv.includes('--build'))
      run('docker', [...baseCompose, '--profile', 'full', 'build', 'api', 'gctree', 'clonaltree', 'dowser', 'brepphylo']);
    run('docker', [...instrumented, 'build', 'api', 'gctree', 'clonaltree']);
    run('docker', [...instrumented, 'up', '-d', '--wait']);
    run(python, ['scripts/wait-test-methods.py']);
    run(python, ['-m', 'pytest', '-c', 'pytest.ini', 'tests/e2e', '-q', '--junitxml=coverage/scientific/junit.xml']);
    run('npx', ['playwright', 'test']);
    run('node', ['scripts/combine-web-coverage.mjs']);
    run('docker', [...instrumented, 'stop', '-t', '30', 'api', 'worker', 'gctree', 'clonaltree']);
    run(python, ['scripts/combine-python-coverage.py']);
    run('node', ['scripts/test-r.mjs']);
    run(python, ['scripts/check-coverage.py', '--full']);
  }
} catch (error) {
  failed = true;
  console.error(error.message);
} finally {
  const logs = spawnSync('docker', [...baseCompose, '--profile', 'full', 'logs', '--no-color'], {encoding: 'utf8', maxBuffer: 100 * 1024 * 1024});
  fs.mkdirSync('coverage', {recursive: true});
  fs.writeFileSync('coverage/docker.log', (logs.stdout || '') + (logs.stderr || ''));
  if (!keep) {
    const cleanup = spawnSync('docker', [...baseCompose, '--profile', 'full', 'down', '-v'], {stdio: 'inherit'});
    if (cleanup.status !== 0) failed = true;
  }
}
process.exitCode = failed ? 1 : 0;
