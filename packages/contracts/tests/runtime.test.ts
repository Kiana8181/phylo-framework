import { describe, expect, it } from 'vitest';
import { API_ROUTES, withBase } from '../src/index';
import { isEnvelope } from '../src/index';
import { humanizeStage, stageSequenceForMethod } from '../src/index';

describe('public client contract', () => {
  it.each(Object.entries(API_ROUTES))('%s returns a safe absolute API path', (_, route) => {
    const path = (route as (...args: string[]) => string)('a/b ?#', 'x/y');
    expect(path).toMatch(/^\//);
    expect(path).not.toContain('a/b');
    expect(path).not.toContain('x/y');
    expect(path).not.toContain('#');
    expect(path).not.toContain(' ');
  });
  it('encodes run and tree identifiers independently', () => {
    expect(API_ROUTES.runTree('a/b', 'x y')).toBe('/runs/a%2Fb/trees/x%20y');
    expect(API_ROUTES.createRun('a&b')).toBe('/runs?method=a%26b');
    expect(API_ROUTES.runQuota()).toBe('/runs/quota');
  });
  it.each([['http://api///', '///runs', 'http://api/runs'], ['', '/runs', '/runs']])('joins URL %s %s', (a, b, expected) => {
    expect(withBase(a, b)).toBe(expected);
  });
  it.each([null, undefined, '', 0, {}, {status: 'success'}])('rejects incomplete envelope %j', value => {
    expect(isEnvelope(value)).toBe(false);
  });
  it('recognizes envelopes with null data', () => expect(isEnvelope({status: 'error', data: null})).toBe(true));
  it.each(['gctree', 'clonaltree', 'dowser', 'brepphylo', 'future', null])('has consistent stage ordering for %s', method => {
    const stages = stageSequenceForMethod(method);
    expect(stages[0].id).toBe('QUEUED');
    expect(stages.at(-1)?.id).toBe('COMPLETED');
    expect(new Set(stages.map(s => s.id)).size).toBe(stages.length);
    expect(stages.every(s => humanizeStage(s.id) === s.label)).toBe(true);
  });
  it('humanizes unknown and absent stages', () => {
    expect(humanizeStage('NEW_STEP')).toBe('New step');
    expect(humanizeStage(null)).toBe('');
  });
});
