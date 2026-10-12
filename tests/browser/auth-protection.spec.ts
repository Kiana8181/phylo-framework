import { test, expect, confirmationLink, signup } from './fixtures';
import crypto from 'node:crypto';

const api = 'http://127.0.0.1:58000';

test('sign-in protection: proof-of-work check, email confirmation, and what an unconfirmed account can do', async ({page, request}) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/auth/);

  // The API refuses the form without the check: the browser really has to solve it.
  const tag = crypto.randomUUID().replaceAll('-', '');
  const email = `${tag}@example.org`;
  const password = 'browser-password-123';
  const bare = await request.post(`${api}/auth/login`, {data: {email, password}});
  expect(bare.status()).toBe(400);
  expect((await bare.json()).data.code).toBe('CAPTCHA_REQUIRED');

  // Sign up. The browser solves the check; the answer is a neutral "check your email".
  await page.goto('/auth?mode=signup');
  await page.getByLabel('Email', {exact: true}).fill(email);
  await page.getByLabel('Username', {exact: true}).fill(tag);
  await page.getByLabel('Password', {exact: true}).fill(password);
  const submitted = page.waitForResponse(r => r.url().endsWith('/auth/register') && r.request().method() === 'POST');
  await page.getByRole('button', {name: 'Sign up', exact: true}).click();
  const registration = await submitted;
  expect(registration.status()).toBe(202);
  const sent = registration.request().postDataJSON();
  expect(typeof sent.captcha.challenge).toBe('string');
  expect(Number.isInteger(sent.captcha.counter)).toBe(true);
  await expect(page.getByTestId('check-your-email')).toContainText(email);
  expect(await page.evaluate(() => localStorage.getItem('phylo_access_token'))).toBeNull();   // not signed in
  const firstLink = new URL(await confirmationLink(page, email));

  // Log in without confirming: allowed, with a banner saying what is missing.
  await page.getByRole('button', {name: 'Back to Log in'}).click();
  await page.getByLabel('Email', {exact: true}).fill(email);
  await page.getByLabel('Password', {exact: true}).fill(password);
  await page.locator('form').getByRole('button', {name: 'Log in', exact: true}).click();
  await expect(page).toHaveURL(/\/dashboard/);
  const banner = page.getByTestId('verify-email-banner');
  await expect(banner).toContainText('Confirm your email address to upload data and start runs.');
  await expect(banner).toContainText(email);

  // The server enforces it, whatever the page shows.
  const token = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  const headers = {Authorization: `Bearer ${token}`};
  const upload = await request.post(`${api}/uploads/init`, {headers, data: {original_filename: 'x.fa'}});
  expect(upload.status()).toBe(403);
  expect((await upload.json()).data.code).toBe('EMAIL_NOT_VERIFIED');
  expect((await request.get(`${api}/runs`, {headers})).status()).toBe(200);                    // reading is fine

  // Ask for a new link: the old one stops working, the new one confirms and signs in.
  await banner.getByRole('button', {name: 'Send a new link'}).click();
  await expect(page.getByText(`We sent a new confirmation link to ${email}.`)).toBeVisible();
  let newLink = firstLink;
  await expect.poll(async () => {
    newLink = new URL(await confirmationLink(page, email));
    return newLink.search !== firstLink.search;
  }, {timeout: 20_000}).toBe(true);

  await page.goto(firstLink.pathname + firstLink.search);
  await expect(page.getByTestId('verify-email-error')).toBeVisible();

  await page.goto(newLink.pathname + newLink.search);
  await expect(page).toHaveURL(/\/dashboard/);
  // Wait for the dashboard itself (the run wizard), then check the banner is gone.
  await expect(page.getByTestId('run-quota-usage')).toBeVisible();
  await expect(page.getByTestId('verify-email-banner')).toHaveCount(0);
  const confirmed = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  const allowed = await request.post(`${api}/uploads/init`, {headers: {Authorization: `Bearer ${confirmed}`}, data: {original_filename: 'x.fa'}});
  expect(allowed.status()).toBe(200);
});

test('password reset through the form: the emailed link sets a new password and ends the old session', async ({page, request}) => {
  await page.goto('/dashboard');
  await expect(page).toHaveURL(/\/auth/);
  const {email, password} = await signup(page);
  const oldToken = await page.evaluate(() => localStorage.getItem('phylo_access_token'));
  await page.evaluate(() => localStorage.clear());
  await page.waitForTimeout(1100);                                    // session times are whole seconds

  await page.goto('/auth/forgot-password');
  await page.getByLabel('Email', {exact: true}).fill(email);
  await page.getByRole('button', {name: 'Send reset link'}).click();
  await expect(page.getByText('If an account exists with that email', {exact: false})).toBeVisible();

  let resetLink: URL | null = null;
  await expect.poll(async () => {
    const {messages} = await (await request.get('http://127.0.0.1:58025/messages')).json();
    const mine = messages.filter((m: {recipients: string[]; subject: string}) => m.recipients.includes(email) && m.subject.startsWith('Reset your'));
    const found = mine.length ? mine[mine.length - 1].text.match(/https?:\/\/\S+reset-password\?token=\S+/)?.[0] : null;
    resetLink = found ? new URL(found) : null;
    return resetLink !== null;
  }, {timeout: 30_000}).toBe(true);

  await page.goto(resetLink!.pathname + resetLink!.search);
  const fields = page.locator('input[type="password"]');
  const count = await fields.count();
  for (let i = 0; i < count; i++) await fields.nth(i).fill('a-brand-new-password-7');
  await page.locator('form').getByRole('button').first().click();
  await expect(page.getByText('Password reset. You can now log in.', {exact: false}).first()).toBeVisible();
  await expect(page).toHaveURL(/\/auth$/);

  // The session from before the reset no longer works; the old password neither.
  expect((await request.get(`${api}/auth/me`, {headers: {Authorization: `Bearer ${oldToken}`}})).status()).toBe(401);
  await page.getByLabel('Email', {exact: true}).fill(email);
  await page.getByLabel('Password', {exact: true}).fill(password);
  await page.locator('form').getByRole('button', {name: 'Log in', exact: true}).click();
  await expect(page.getByText('Incorrect email or password', {exact: false})).toBeVisible();
  await page.getByLabel('Password', {exact: true}).fill('a-brand-new-password-7');
  await page.locator('form').getByRole('button', {name: 'Log in', exact: true}).click();
  await expect(page).toHaveURL(/\/dashboard/);
});
