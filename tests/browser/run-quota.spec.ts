import { test, expect, signup } from './fixtures';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const api = 'http://127.0.0.1:58000';
const root = process.cwd();   // tests run from the repository root
const sample = readFileSync(path.join(root, 'apps/web/public/samples/ExampleAirr_clone_3128.tsv'));
const params = JSON.parse(readFileSync(path.join(root, 'tests/fixtures/scientific-params.json'), 'utf8'));

test('the hourly run limit disables new runs, shows a countdown, and lifts when a queued run is cancelled', async ({page, request}) => {
  // Load the dashboard route once first (it redirects to sign-in): the dev
  // server compiles a route on first use, which must not eat into the wait
  // for the redirect that follows sign-up.
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/auth/);
  await signup(page);
  const token = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  const headers = {Authorization: `Bearer ${token}`};

  // Before any run: the wizard shows the allowance and Run is available.
  await expect(page.getByTestId('run-quota-usage')).toHaveText('0 of 5 runs used this hour');

  const init = await (await request.post(`${api}/uploads/init`, {headers, data: {original_filename: 'quota-sample.tsv'}})).json();
  const file = await (await request.put(`${api}${init.content_url}`, {headers, data: sample})).json();
  const create = () => request.post(`${api}/runs?method=dowser`, {headers, data: {file_id: file.file_id, params: params.dowser}});

  // Five runs are accepted (one starts, four wait); the sixth is refused by the server.
  const runIds: string[] = [];
  for (let i = 0; i < 5; i++) {
    const response = await create();
    expect(response.status(), `run ${i + 1}`).toBe(200);
    runIds.push((await response.json()).run_id);
  }
  const refused = await create();
  expect(refused.status()).toBe(429);
  const body = await refused.json();
  expect(body.data.code).toBe('RUN_QUOTA_EXCEEDED');
  expect(Number(refused.headers()['retry-after'])).toBeGreaterThan(3500);

  // The dashboard says so: a notice with a countdown, and no way to add a run.
  await page.goto('/dashboard');
  const notice = page.getByTestId('run-quota-blocked');
  await expect(notice).toBeVisible();
  await expect(notice).toContainText('Hourly run limit reached');
  await expect(notice).toContainText('limit of 5 runs per hour');
  await expect(page.getByTestId('run-quota-countdown')).toHaveText(/^5\d:\d\d$/);
  const first = await page.getByTestId('run-quota-countdown').textContent();
  await expect(page.getByTestId('run-quota-countdown')).not.toHaveText(first!);     // it is counting down
  await expect(page.getByRole('button', {name: 'Add run'})).toBeDisabled();

  // Cancelling a run that has not started gives its allowance back.
  const cancelled = await request.post(`${api}/runs/${runIds[4]}/cancel-queued`, {headers});
  expect((await cancelled.json()).status).toBe('CANCELLED');
  await page.reload();
  await expect(page.getByTestId('run-quota-blocked')).toHaveCount(0);
  const addRun = page.getByRole('button', {name: 'Add run'});
  await expect(addRun).toBeEnabled();
  await addRun.click();
  await expect(page.getByTestId('run-quota-usage')).toHaveText('4 of 5 runs used this hour');

  // Leave nothing running for the tests that follow.
  for (const id of runIds.slice(0, 4)) await request.post(`${api}/runs/${id}/cancel`, {headers});
});
