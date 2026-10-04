import { test, expect, type Page } from './fixtures';
import { randomUUID } from 'node:crypto';
const api = 'http://127.0.0.1:58000';

async function signup(page: Page) {
  const tag = randomUUID().replaceAll('-', '');
  await page.goto('/auth?mode=signup');
  await page.getByLabel('Email', {exact: true}).fill(`${tag}@example.org`);
  await page.getByLabel('Username', {exact: true}).fill(tag);
  await page.getByLabel('Password', {exact: true}).fill('browser-password-123');
  await page.getByRole('button', {name: 'Sign up', exact: true}).click();
  await expect(page).toHaveURL(/\/dashboard/);
  return {email: `${tag}@example.org`, password: 'browser-password-123'};
}

test('protected dashboard redirects; real signup and login persist across reload', async ({page}) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/auth/);
  const credentials = await signup(page);
  await page.reload();
  await expect(page).toHaveURL(/\/dashboard/);
  await page.evaluate(() => localStorage.clear());
  await page.goto('/auth');
  await page.getByLabel('Email', {exact: true}).fill(credentials.email);
  await page.getByLabel('Password', {exact: true}).fill('wrong-password');
  await page.locator('form').getByRole('button', {name: 'Log in', exact: true}).click();
  await expect(page.getByText('Incorrect email or password', {exact: false})).toBeVisible();
  await page.getByLabel('Password', {exact: true}).fill(credentials.password);
  await page.locator('form').getByRole('button', {name: 'Log in', exact: true}).click();
  await expect(page).toHaveURL(/\/dashboard/);
});

test('file management renders real uploads and deletes with confirmation', async ({page, request}) => {
  await signup(page);
  const token = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  const headers = {Authorization: `Bearer ${token}`};
  const response = await request.post(`${api}/uploads/init`, {headers, data: {original_filename: 'browser-sample.fa'}});
  expect(response.ok()).toBe(true);
  const init = await response.json();
  const uploaded = await request.put(`${api}${init.content_url}`, {headers, data: Buffer.from('>root\nACGT\n>a\nACGA\n')});
  expect(uploaded.ok()).toBe(true);
  const file = await uploaded.json();
  await page.goto('/dashboard/files');
  await expect(page.getByText('browser-sample.fa', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Delete browser-sample.fa'}).click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  await dialog.getByRole('button', {name: /delete/i}).click();
  await expect(page.getByText('No files yet.', {exact: false})).toBeVisible();
  expect((await request.get(`${api}/datasets/${file.file_id}/download`, {headers})).status()).toBe(410);
});

for (const method of ['Dowser', 'GCtree', 'ClonalTree', 'BrepPhylo']) {
test(`documented ${method} example completes and renders its tree`, async ({page}) => {
  await signup(page);
  await page.goto('/documents/try-it-yourself');
  await page.getByRole('button', {name: new RegExp(`try.*${method}`, 'i')}).click();
  await expect(page).toHaveURL(/\/dashboard/);
  const submission = page.waitForResponse(r => r.url().includes('/runs?method=') && r.request().method() === 'POST');
  await page.getByRole('button', {name: /^run$/i}).click();
  const response = await submission;
  expect(response.ok()).toBe(true);
  const {run_id} = await response.json();
  const token = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  await expect.poll(async () => {
    const status = await page.request.get(`${api}/runs/${run_id}/status`, {headers: {Authorization: `Bearer ${token}`}});
    return (await status.json()).status;
  }, {timeout: 150_000, intervals: [500, 1000]}).toBe('DONE');
  await page.goto(`/dashboard?runId=${run_id}`);
  await expect(page.getByRole('heading', {name: 'Results', exact: true})).toBeVisible();
  await expect(page.getByText('Downloads', {exact: true})).toBeVisible();
  await expect(page.locator('svg').filter({has: page.locator('text')} ).first()).toBeVisible();
});

}
