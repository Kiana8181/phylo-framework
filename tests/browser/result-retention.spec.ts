import { test, expect, signup, runStatus } from './fixtures';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const api = 'http://127.0.0.1:58000';
const root = process.cwd();   // tests run from the repository root
const sample = readFileSync(path.join(root, 'apps/web/public/samples/ExampleAirr_clone_3128.tsv'));
const params = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/scientific-params.json'), 'utf8'));

/** Move one run's expiry date into the past. The test stack looks for expired
 *  results every 2 seconds; everything after this is the application's doing. */
function letTheDatePass(runId: string) {
  if (!/^[0-9a-f-]{36}$/.test(runId)) throw new Error(`not a run id: ${runId}`);
  execFileSync('docker', ['compose', '-f', 'docker-compose.test.yml', 'exec', '-T', 'postgres', 'psql', '-U', 'phylo_test',
    '-d', 'phylo_e2e_test', '-v', 'ON_ERROR_STOP=1', '-c',
    `UPDATE runs SET expires_at = now() - interval '1 minute' WHERE id = '${runId}'`], {cwd: root, stdio: 'pipe'});
}

test('a finished run shows until when its results are kept, and explains itself once they have expired', async ({page, request}) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/auth/);
  await signup(page);
  const token = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  const headers = {Authorization: `Bearer ${token}`};

  const init = await (await request.post(`${api}/uploads/init`, {headers, data: {original_filename: 'retention-sample.tsv'}})).json();
  const file = await (await request.put(`${api}${init.content_url}`, {headers, data: sample})).json();
  const created = await request.post(`${api}/runs?method=gctree`, {headers, data: {file_id: file.file_id, params: params.gctree}});
  expect(created.ok()).toBe(true);
  const {run_id: runId} = await created.json();
  const status = () => runStatus(request, runId, token);
  await expect.poll(async () => (await status()).status, {timeout: 150_000, intervals: [500, 1000]}).toBe('DONE');
  const until = (await status()).expires_at.slice(0, 10);

  // Before the date: the run page and the history both say until when.
  await page.goto(`/dashboard?runId=${runId}`);
  const notice = page.getByTestId('result-retention');
  await expect(notice).toHaveAttribute('data-state', 'kept');
  await expect(notice).toContainText(`These results are kept until ${until}`);
  await expect(notice).toContainText(/\((59|60) days left\)/);
  await expect(page.getByText('Downloads', {exact: true})).toBeVisible();
  await page.goto('/dashboard/history');
  await expect(page.getByTestId('run-results-kept-until')).toHaveText(`kept until ${until}`);
  await expect(page.getByTestId('run-results-expired')).toHaveCount(0);

  letTheDatePass(runId);
  await expect.poll(async () => (await status()).results_expired, {timeout: 60_000, intervals: [500, 1000]}).toBe(true);

  // After the date: still in the history, marked, and no longer comparable.
  await page.reload();
  await expect(page.getByTestId('run-results-expired')).toHaveText('Results expired');
  await expect(page.getByTestId('run-results-kept-until')).toHaveCount(0);
  await expect(page.getByRole('button', {name: /sequence trace/i})).toHaveCount(0);

  // Its page explains what happened and still shows what was run.
  await page.getByRole('button', {name: /view details/i}).click();
  await expect(page).toHaveURL(new RegExp(`runId=${runId}`));
  await expect(notice).toHaveAttribute('data-state', 'expired');
  await expect(notice).toContainText(/The results of this run expired on \d{4}-\d{2}-\d{2} and were removed\./);
  await expect(notice).toContainText('To get the results again, run it again.');
  await expect(page.getByRole('heading', {name: 'Run Summary'})).toBeVisible();
  await expect(page.getByText(runId, {exact: true})).toBeVisible();
  await expect(page.getByText('Downloads', {exact: true})).toHaveCount(0);
  await expect(page.getByRole('heading', {name: 'Results', exact: true})).toHaveCount(0);
  // The page did not go on asking for things that are gone.
  const refused: string[] = [];
  page.on('response', r => { if (r.status() === 410) refused.push(r.url()); });
  await page.reload();
  await expect(notice).toHaveAttribute('data-state', 'expired');
  expect(refused).toEqual([]);
});
