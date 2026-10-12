// @vitest-environment jsdom
import {cleanup, render, screen} from '@testing-library/react';
import {afterEach, expect, it} from 'vitest';
import ResultRetentionNotice from '../ResultRetentionNotice';

const NOW = Date.parse('2026-10-12T09:00:00Z');
const inDays = (days: number) => new Date(NOW + days * 86_400_000).toISOString();
const notice = () => screen.getByTestId('result-retention');

afterEach(cleanup);

it('shows nothing when results are kept for ever or the run has not ended', () => {
  for (const run of [undefined, null, {}, {expires_at: null, results_expired: false}]) {
    const {container} = render(<ResultRetentionNotice run={run} now={NOW} />);
    expect(container.innerHTML).toBe('');
    cleanup();
  }
});

it('says until when the results are kept, before the date', () => {
  render(<ResultRetentionNotice run={{expires_at: inDays(60), results_expired: false}} now={NOW} />);
  expect(notice().getAttribute('data-state')).toBe('kept');
  expect(notice().textContent).toContain('These results are kept until 2026-12-11 (60 days left).');
  expect(notice().textContent).toContain('Download what you need before then; after that date they are removed.');
});

it('draws attention in the last week', () => {
  render(<ResultRetentionNotice run={{expires_at: inDays(2.5)}} now={NOW} />);
  expect(notice().getAttribute('data-state')).toBe('soon');
  expect(notice().textContent).toContain('(2 days left)');
  expect(notice().className).toContain('amber');
});

it('says so when the date has passed and removal is imminent', () => {
  render(<ResultRetentionNotice run={{expires_at: inDays(-0.1), results_expired: false}} now={NOW} />);
  expect(notice().getAttribute('data-state')).toBe('due');
  expect(notice().textContent).toContain('will be removed shortly');
});

it('explains an expired run: what happened, when, and what is left', () => {
  render(<ResultRetentionNotice run={{expires_at: inDays(-1), results_expired: true, results_expired_at: inDays(-1)}} now={NOW} />);
  expect(notice().getAttribute('data-state')).toBe('expired');
  expect(notice().getAttribute('role')).toBe('status');
  expect(notice().textContent).toContain('The results of this run expired on 2026-10-11 and were removed.');
  expect(notice().textContent).toContain('The run stays in your history with its settings.');
  expect(notice().textContent).toContain('To get the results again, run it again.');
});

it('speaks of the log for a failed run', () => {
  render(<ResultRetentionNotice run={{expires_at: inDays(30)}} what="log" now={NOW} />);
  expect(notice().textContent).toBe('The log of this run is kept until 2026-11-11 (30 days left).');
  cleanup();
  render(<ResultRetentionNotice run={{results_expired: true, results_expired_at: inDays(-3)}} what="log" now={NOW} />);
  expect(notice().textContent).toContain('The log of this run expired on 2026-10-09 and was removed.');
  expect(notice().textContent).not.toContain('run it again');
});
