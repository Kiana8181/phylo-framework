// @vitest-environment jsdom
import { act, renderHook } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { useUploadSession } from '../hooks';
import { UploadsApi } from '../api';
vi.mock('../api', () => ({UploadsApi: {init: vi.fn(), content: vi.fn(), cancel: vi.fn()}}));
const api = vi.mocked(UploadsApi);
const file = new File(['ACGT'], 'sample.fa', {type: 'text/plain'});
beforeEach(() => {
  vi.resetAllMocks();
  api.init.mockResolvedValue({upload_id: 'u1', content_url: '/uploads/u1/content', status: 'INITIATED'});
  api.cancel.mockResolvedValue();
});
it('tracks progress and returns the uploaded file', async () => {
  let resolve!: (value: any) => void;
  api.content.mockImplementation((_id, _file, progress) => {
    progress(50);
    return {promise: new Promise(r => {resolve = r;}), abort: vi.fn()};
  });
  const {result} = renderHook(() => useUploadSession());
  let pending!: Promise<any>;
  await act(async () => {pending = result.current.upload(file);});
  expect(result.current.uploading).toBe(true);
  expect(result.current.progress).toBe(50);
  await act(async () => {resolve({file_id: 'f1'}); await pending;});
  expect(result.current.uploading).toBe(false);
  expect(result.current.progress).toBe(100);
  expect(api.cancel).not.toHaveBeenCalled();
});
it('aborts the network request and cleans the session on cancel', async () => {
  let reject!: (error: Error) => void;
  const abort = vi.fn(() => reject(new Error('aborted')));
  api.content.mockReturnValue({promise: new Promise((_r, j) => {reject = j;}), abort});
  const {result} = renderHook(() => useUploadSession());
  let pending!: Promise<any>;
  await act(async () => {pending = result.current.upload(file).catch(e => e);});
  await act(async () => {await result.current.cancel(); await pending;});
  expect(abort).toHaveBeenCalledOnce();
  expect(api.cancel).toHaveBeenCalledWith('u1');
  expect(result.current.uploading).toBe(false);
  expect(result.current.uploadId).toBeNull();
});
it('cleans a failed upload even when server cleanup fails', async () => {
  api.content.mockReturnValue({promise: Promise.reject(new Error('network failed')), abort: vi.fn()});
  api.cancel.mockRejectedValue(new Error('cleanup failed'));
  const {result} = renderHook(() => useUploadSession());
  await act(async () => {await expect(result.current.upload(file)).rejects.toThrow('network failed');});
  expect(api.cancel).toHaveBeenCalledWith('u1');
  expect(result.current.uploading).toBe(false);
});
