import {test as base, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

export const test = base.extend<{coverage: void}>({
  coverage: [async ({page}, use, testInfo) => {
    const directory = path.resolve('coverage/browser-raw');
    fs.mkdirSync(directory, {recursive: true});
    let counter = 0;
    await page.exposeFunction('__saveTestCoverage', (coverage: unknown) => {
      fs.writeFileSync(path.join(directory, `${testInfo.testId.replace(/[^\w-]/g, '_')}-${counter++}.json`), JSON.stringify(coverage));
    });
    await page.addInitScript(() => {
      window.addEventListener('beforeunload', () => {
        const win = window as any;
        if (win.__coverage__) void win.__saveTestCoverage(win.__coverage__);
      });
    });
    await use();
    const data = await page.evaluate(() => (window as any).__coverage__);
    expect(data, 'browser instrumentation must produce coverage').toBeTruthy();
    fs.writeFileSync(path.join(directory, `${testInfo.testId.replace(/[^\w-]/g, '_')}-final.json`), JSON.stringify(data));
  }, {auto: true}],
});
export {expect};
export type {Page};

const MAIL = 'http://127.0.0.1:58025';

/** The newest confirmation link emailed to `address`, read from the test mail server. */
export async function confirmationLink(page: Page, address: string): Promise<string> {
  let link: string | null = null;
  await expect.poll(async () => {
    const response = await page.request.get(`${MAIL}/messages`);
    const {messages} = await response.json();
    const mine = messages.filter((m: {recipients: string[]; subject: string}) =>
      m.recipients.includes(address) && m.subject.startsWith('Confirm your'));
    if (!mine.length) return false;
    link = mine[mine.length - 1].text.match(/https?:\/\/\S+verify-email\?token=\S+/)?.[0] ?? null;
    return link !== null;
  }, {timeout: 30_000, intervals: [200, 500]}).toBe(true);
  return link!;
}

/**
 * Create an account the way a person does: fill in the sign-up form (the
 * browser solves the proof-of-work check on submit), then open the emailed
 * confirmation link, which signs in and lands on the dashboard.
 */
export async function signup(page: Page): Promise<{email: string; password: string}> {
  const tag = crypto.randomUUID().replaceAll('-', '');
  const email = `${tag}@example.org`;
  const password = 'browser-password-123';
  await page.goto('/auth?mode=signup');
  await page.getByLabel('Email', {exact: true}).fill(email);
  await page.getByLabel('Username', {exact: true}).fill(tag);
  await page.getByLabel('Password', {exact: true}).fill(password);
  await page.getByRole('button', {name: 'Sign up', exact: true}).click();
  // Not signed in yet: the form says a link was sent.
  await expect(page.getByTestId('check-your-email')).toContainText(email);
  const link = new URL(await confirmationLink(page, email));
  await page.goto(link.pathname + link.search);
  await expect(page).toHaveURL(/\/dashboard/);
  return {email, password};
}
