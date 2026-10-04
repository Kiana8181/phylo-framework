import {test as base, expect, type Page} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

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
