import {expect, it} from 'vitest';
import {
  daysLeftLabel, isResultExpiredError, isUploadTooLargeError, retentionDate, retentionState,
} from '../retention';

const NOW = Date.parse('2026-10-12T09:00:00Z');
const inDays = (days: number) => new Date(NOW + days * 86_400_000).toISOString();

it('says nothing for a run without an expiry date', () => {
  for (const run of [null, undefined, {}, {expires_at: null}, {expires_at: 'not a date'}]) {
    expect(retentionState(run, NOW)).toEqual({kind: 'none'});
  }
});

it('counts whole days left and highlights the last week', () => {
  expect(retentionState({expires_at: inDays(60)}, NOW)).toEqual(
    {kind: 'kept', until: '2026-12-11', daysLeft: 60, soon: false, due: false});
  expect(retentionState({expires_at: inDays(7)}, NOW)).toMatchObject({daysLeft: 7, soon: false});
  expect(retentionState({expires_at: inDays(6.9)}, NOW)).toMatchObject({daysLeft: 6, soon: true});
  expect(retentionState({expires_at: inDays(0.2)}, NOW)).toMatchObject({daysLeft: 0, soon: true, due: false});
});

it('a date that has passed but is not yet acted on is "due", not "expired"', () => {
  expect(retentionState({expires_at: inDays(-0.5), results_expired: false}, NOW)).toMatchObject(
    {kind: 'kept', daysLeft: 0, due: true});
});

it('reports expired results with the date they went', () => {
  expect(retentionState({expires_at: inDays(-2), results_expired: true, results_expired_at: inDays(-1)}, NOW))
    .toEqual({kind: 'expired', on: '2026-10-11'});
  expect(retentionState({expires_at: inDays(-2), results_expired: true}, NOW)).toEqual({kind: 'expired', on: '2026-10-10'});
  expect(retentionState({results_expired: true}, NOW)).toEqual({kind: 'expired', on: null});
});

it('uses the same calendar date as the email and the API (UTC)', () => {
  expect(retentionDate('2026-12-11T23:59:59+00:00')).toBe('2026-12-11');
  expect(retentionDate('2026-12-11T23:30:00-03:00')).toBe('2026-12-12');
  expect(retentionDate(null)).toBeNull();
  expect(retentionDate('junk')).toBeNull();
});

it('words the time left', () => {
  expect(daysLeftLabel(58)).toBe('58 days left');
  expect(daysLeftLabel(1)).toBe('1 day left');
  expect(daysLeftLabel(0)).toBe('less than a day left');
});

it('recognises the API refusals by their code', () => {
  expect(isResultExpiredError({message: 'x', data: {code: 'RESULT_EXPIRED'}})).toBe(true);
  expect(isUploadTooLargeError({message: 'x', data: {code: 'UPLOAD_TOO_LARGE', max_upload_bytes: 1}})).toBe(true);
  for (const other of [null, undefined, new Error('x'), {data: {code: 'QUEUE_FULL'}}, {data: null}]) {
    expect(isResultExpiredError(other)).toBe(false);
    expect(isUploadTooLargeError(other)).toBe(false);
  }
});
