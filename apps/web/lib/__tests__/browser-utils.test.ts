// @vitest-environment jsdom
import {beforeEach, expect, it, vi} from 'vitest';
import {clearTokens, getAccessToken, getRefreshToken, getStoredUser, setTokens} from '../auth/storage';
import {getApiErrorMessage, isAuthRequestUrl} from '../http/errors';
import {parseNewick, cleanNewick} from '../newick';
beforeEach(() => localStorage.clear());
it('stores tokens and user, clears all identity data on logout', () => {
  expect(getAccessToken()).toBeNull();
  expect(getRefreshToken()).toBeNull();
  expect(getStoredUser()).toBeNull();
  const user = {id: 'u', username: 'a', email: 'a@example.org'};
  setTokens('access', 'refresh', user);
  expect(getAccessToken()).toBe('access');
  expect(getRefreshToken()).toBe('refresh');
  expect(getStoredUser()).toEqual(user);
  clearTokens();
  expect(getAccessToken()).toBeNull();
  expect(getStoredUser()).toBeNull();
});
it('recovers from corrupt user storage and does not erase user on token-only refresh', () => {
  localStorage.setItem('phylo_user', '{broken');
  expect(getStoredUser()).toBeNull();
  setTokens('a', 'r', {id: 'u', email: 'a@example.org', username: 'a'});
  setTokens('new', 'new-refresh');
  expect(getStoredUser()?.id).toBe('u');
});
it.each([
  [{response: {data: {status: 'error', data: null, message: 'quota exceeded'}}}, 'quota exceeded'],
  [{response: {data: {status: 'error', data: [{msg: 'bad sequence'}], message: 'Validation error'}}}, 'bad sequence'],
  [{response: {data: {detail: [{msg: 'bad input'}]}}}, 'bad input'],
  [{response: {data: {detail: ['bad input']}}}, 'bad input'],
  [{response: {data: {detail: 'missing'}}}, 'missing'],
  [{response: {data: {error: 'service offline'}}}, 'service offline'],
  [new Error('Network error'), 'Network error'],
  [null, 'fallback'],
  [{message: 'Request failed with status code 500'}, 'fallback'],
])('extracts meaningful API errors', (error, expected) => {
  expect(getApiErrorMessage(error, 'fallback')).toBe(expected);
});
it.each(['/auth/login', '/auth/register', '/auth/google', '/auth/forgot-password', '/auth/reset-password'])('recognizes auth request %s', url => {
  expect(isAuthRequestUrl(url)).toBe(true);
});
it.each([undefined, '', '/runs'])('does not treat %s as auth', url => expect(isAuthRequestUrl(url)).toBe(false));
it('parses nested scientific trees preserving labels, topology, zero and exponential branch lengths', () => {
  expect(parseNewick(' ((a:0,b:1e-3)internal:2,c:3)root; ')).toEqual({name: 'root', children: [
    {name: 'internal', length: 2, children: [{name: 'a', length: 0}, {name: 'b', length: 0.001}]},
    {name: 'c', length: 3},
  ]});
  expect(cleanNewick('[1] "(a,b)"')).toBe('(a,b);');
  expect(cleanNewick('(a,b);')).toBe('(a,b);');
});
it('rejects unbalanced Newick', () => expect(() => parseNewick('((a,b);')).toThrow());
