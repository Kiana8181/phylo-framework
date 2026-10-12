// @vitest-environment jsdom
import {act, cleanup, render, screen} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import type {RunQuotaResponse} from '@phylo/contracts';
import RunQuotaNotice from '../RunQuotaNotice';

const SERVER_NOW = '2026-01-01T12:00:00+00:00';
const T0 = Date.parse(SERVER_NOW);
const window_ = (over = {}) => ({limit: 5, used: 0, remaining: 5, window_seconds: 3600, reset_at: null, retry_after_seconds: null, ...over});
const quota = (over: Partial<RunQuotaResponse> = {}): RunQuotaResponse => ({
  can_submit: true, blocked_by: null, message: null, retry_after_seconds: null,
  hourly: window_(), submissions: window_({limit: 30, remaining: 30}),
  queue: {max_queued: 5, queued_count: 0, unfinished: 0, can_add: true},
  server_time: SERVER_NOW, ...over,
});
const blocked = (seconds: number) => quota({
  can_submit: false, blocked_by: 'RUN_QUOTA_EXCEEDED',
  message: 'You have reached the limit of 5 runs per hour. You can start another run when the oldest of them is an hour old.',
  retry_after_seconds: seconds,
  hourly: window_({used: 5, remaining: 0, reset_at: new Date(T0 + seconds * 1000).toISOString(), retry_after_seconds: seconds}),
});

beforeEach(() => { vi.useFakeTimers(); vi.setSystemTime(T0); });
afterEach(() => { cleanup(); vi.useRealTimers(); });

it('shows nothing until the quota is known', () => {
  const {container} = render(<RunQuotaNotice quota={undefined} fetchedAt={0} />);
  expect(container.innerHTML).toBe('');
});

it('shows the allowance quietly while a run can be submitted', () => {
  render(<RunQuotaNotice quota={quota({hourly: window_({used: 3, remaining: 2})})} fetchedAt={T0} />);
  expect(screen.getByTestId('run-quota-usage').textContent).toBe('3 of 5 runs used this hour');
  expect(screen.queryByTestId('run-quota-blocked')).toBeNull();
});

it('shows nothing when there is no hourly limit and nothing blocks', () => {
  const {container} = render(<RunQuotaNotice quota={quota({hourly: window_({limit: null, remaining: null})})} fetchedAt={T0} />);
  expect(container.innerHTML).toBe('');
});

it('explains a reached hourly limit and counts down to the next possible run', () => {
  const onReset = vi.fn();
  render(<RunQuotaNotice quota={blocked(125)} fetchedAt={T0} onReset={onReset} />);
  const notice = screen.getByRole('status');
  expect(notice.textContent).toContain('Hourly run limit reached');
  expect(notice.textContent).toContain('limit of 5 runs per hour');
  expect(screen.getByTestId('run-quota-countdown').textContent).toBe('2:05');

  act(() => { vi.advanceTimersByTime(65_000); });
  expect(screen.getByTestId('run-quota-countdown').textContent).toBe('1:00');
  expect(onReset).not.toHaveBeenCalled();

  act(() => { vi.advanceTimersByTime(60_000); });
  // The moment has come: ask the server again, once.
  expect(screen.queryByTestId('run-quota-countdown')).toBeNull();
  expect(notice.textContent).toContain('Checking whether you can start a run again');
  expect(onReset).toHaveBeenCalledTimes(1);
  act(() => { vi.advanceTimersByTime(10_000); });
  expect(onReset).toHaveBeenCalledTimes(1);
});

it('asks again for each new reset time, not only the first', () => {
  const onReset = vi.fn();
  const view = render(<RunQuotaNotice quota={blocked(5)} fetchedAt={T0} onReset={onReset} />);
  act(() => { vi.advanceTimersByTime(6_000); });
  expect(onReset).toHaveBeenCalledTimes(1);
  // The server says: still blocked, until a later moment.
  const later = quota({...blocked(0), server_time: new Date(T0 + 6_000).toISOString(),
    hourly: window_({used: 5, remaining: 0, reset_at: new Date(T0 + 16_000).toISOString()})});
  view.rerender(<RunQuotaNotice quota={later} fetchedAt={T0 + 6_000} onReset={onReset} />);
  expect(screen.getByTestId('run-quota-countdown').textContent).toBe('0:10');
  act(() => { vi.advanceTimersByTime(11_000); });
  expect(onReset).toHaveBeenCalledTimes(2);
});

it('does not trust a wrong browser clock for the countdown', () => {
  vi.setSystemTime(T0 + 3 * 3_600_000);                       // browser is three hours ahead of the server
  render(<RunQuotaNotice quota={blocked(600)} fetchedAt={T0 + 3 * 3_600_000} />);
  expect(screen.getByTestId('run-quota-countdown').textContent).toBe('10:00');
});

it('a full queue is explained without a countdown: time alone will not fix it', () => {
  render(<RunQuotaNotice fetchedAt={T0} quota={quota({
    can_submit: false, blocked_by: 'QUEUE_FULL',
    message: 'Your run queue is full (5 queued behind your active run). Wait for a run to finish or cancel a queued one.',
    queue: {max_queued: 5, queued_count: 5, unfinished: 6, can_add: false},
  })} />);
  expect(screen.getByRole('status').textContent).toContain('Your run queue is full');
  expect(screen.queryByTestId('run-quota-countdown')).toBeNull();
});

it('returns to the quiet line once the limit has lifted', () => {
  const view = render(<RunQuotaNotice quota={blocked(30)} fetchedAt={T0} />);
  expect(screen.getByRole('status')).toBeTruthy();
  view.rerender(<RunQuotaNotice quota={quota({hourly: window_({used: 4, remaining: 1})})} fetchedAt={T0 + 31_000} />);
  expect(screen.queryByRole('status')).toBeNull();
  expect(screen.getByTestId('run-quota-usage').textContent).toBe('4 of 5 runs used this hour');
});
