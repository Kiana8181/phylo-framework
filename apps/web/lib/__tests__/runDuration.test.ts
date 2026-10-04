import { expect, it } from 'vitest';
import { formatRunDuration } from '../runDuration';

it.each([[0, '0s'], [59, '59s'], [60, '1m 0s'], [3599, '59m 59s'], [3600, '1h 0m'], [86400, '1d 0h']])('formats %i seconds', (seconds, expected) => {
  expect(formatRunDuration(new Date(0).toISOString(), new Date(seconds * 1000).toISOString())).toBe(expected);
});
it.each([[null, null], ['bad', 'bad'], ['2025-01-02', '2025-01-01'], ['2025-01-01', null]])('rejects missing or invalid interval %s %s', (a, b) => {
  expect(formatRunDuration(a, b)).toBeNull();
});
