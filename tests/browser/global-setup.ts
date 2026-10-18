/**
 * Compile every page of the web app before the first test opens a browser.
 *
 * The tests run against `next dev`, which compiles a page the first time it is
 * requested and then tells every open page "[Fast Refresh] rebuilding". On a
 * busy CI runner that compile took 13 s, and the reload it triggered in the
 * page still open aborted the test's own navigation (net::ERR_ABORTED). With
 * everything compiled here, while no page is open, nothing is left to rebuild
 * during the tests.
 *
 * Pages are found by scanning apps/web/app, so a new page is warmed without
 * touching this file. A new dynamic segment needs an example value below.
 */
import type {FullConfig} from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';

const APP = path.resolve(__dirname, '../../apps/web/app');
const EXAMPLES: Record<string, string> = {'[method]': 'dowser'};

function pages(directory: string, route: string[] = []): string[] {
  const found: string[] = [];
  for (const entry of fs.readdirSync(directory, {withFileTypes: true})) {
    if (entry.isFile() && /^page\.[jt]sx?$/.test(entry.name)) found.push('/' + route.join('/'));
    if (!entry.isDirectory() || entry.name.startsWith('_')) continue;
    let segment: string | null = entry.name;
    if (/^\(.*\)$/.test(segment)) segment = null;                    // route group: not part of the URL
    else if (segment.startsWith('[')) {
      if (!(segment in EXAMPLES)) throw new Error(`global-setup: add an example value for the dynamic route segment ${segment}`);
      segment = EXAMPLES[segment];
    }
    found.push(...pages(path.join(directory, entry.name), segment ? [...route, segment] : route));
  }
  return found;
}

export default async function globalSetup(config: FullConfig) {
  const base = config.projects[0].use.baseURL!;
  for (const route of pages(APP).sort()) {
    const response = await fetch(base + route, {redirect: 'manual', signal: AbortSignal.timeout(180_000)});
    if (response.status >= 500) throw new Error(`global-setup: ${route} answered ${response.status} while warming up`);
  }
}
