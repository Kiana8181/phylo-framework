import { beforeEach, expect, it, vi } from 'vitest';
import { Method, serviceHandler } from '../serviceHandler';
import { http } from '../client';
vi.mock('../client', () => ({http: {request: vi.fn()}}));
beforeEach(() => vi.clearAllMocks());
const request = vi.mocked(http.request);

it.each([{status: 'success', data: {id: 1}}, {id: 1}])('unwraps success and calls callbacks once', async data => {
  request.mockResolvedValue({data});
  const success = vi.fn(), final = vi.fn();
  expect(await serviceHandler({method: Method.Get, url: '/ok', onSuccess: success, onFinal: final})).toEqual({id: 1});
  expect(success).toHaveBeenCalledOnce();
  expect(final).toHaveBeenCalledOnce();
});
it('reports envelope failure once and frees duplicate guard after failure', async () => {
  request.mockResolvedValue({data: {status: 'error', message: 'failed', data: null}});
  const failure = vi.fn(), final = vi.fn();
  await expect(serviceHandler({method: Method.Post, url: '/fail', onFailure: failure, onFinal: final})).rejects.toThrow('failed');
  expect(failure).toHaveBeenCalledOnce();
  expect(final).toHaveBeenCalledOnce();
  request.mockResolvedValue({data: {ok: true}});
  expect(await serviceHandler({method: Method.Post, url: '/fail'})).toEqual({ok: true});
});
it('removes explicit multipart header for converted FormData', async () => {
  request.mockResolvedValue({data: {ok: true}});
  await serviceHandler({method: Method.Post, url: '/upload', data: {name: 'x', ignored: null}, hasFile: true,
    config: {headers: {'Content-Type': 'application/json'}}});
  const config = request.mock.calls[0][0];
  expect(config.data).toBeInstanceOf(FormData);
  expect(config.headers?.['Content-Type']).toBeUndefined();
});
