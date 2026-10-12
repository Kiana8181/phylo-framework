// @vitest-environment jsdom
/** The wizard and the hourly run limit: the server decides, the wizard must
 *  not let the user prepare (or upload for) a run that would be refused. */
import {act, cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import type {MethodInfo, RunQuotaResponse} from '@phylo/contracts';

const mocks = vi.hoisted(() => ({
  create: vi.fn(),
  upload: vi.fn(),
  refetch: vi.fn(),
  notifyError: vi.fn(),
  quota: {current: undefined as unknown},
  parametersProps: {current: null as null | Record<string, any>},
}));

vi.mock('@/features/methods/hooks', () => ({
  useMethodSpec: () => ({data: {id: 'dowser', name: 'Dowser', paramSchema: {type: 'object', properties: {}}, uiHints: {}}, isLoading: false}),
}));
vi.mock('@/features/runs/hooks', () => ({
  useCreateRun: () => ({mutateAsync: mocks.create}),
  useRunQuota: () => ({data: mocks.quota.current, dataUpdatedAt: Date.now(), refetch: mocks.refetch}),
}));
vi.mock('@/features/uploads/hooks', () => ({
  useUploadSession: () => ({upload: mocks.upload, uploading: false, progress: null, cancel: vi.fn()}),
}));
vi.mock('@/lib/notify', () => ({notify: {error: mocks.notifyError, success: vi.fn(), info: vi.fn()}}));
vi.mock('@/components/phylo/MethodsGrid', () => ({default: () => null}));
vi.mock('../DataStep', () => ({
  default: ({onChoose}: {onChoose: (input: unknown) => void}) => (
    <button onClick={() => onChoose({kind: 'upload', file: new File(['ACGT'], 'input.fasta')})}>choose file</button>
  ),
}));
vi.mock('../ParametersStep', () => ({
  default: (props: Record<string, any>) => {
    mocks.parametersProps.current = props;
    return <button onClick={() => props.onRun({seed: 1})}>submit run</button>;
  },
}));

import RunWizard from '../RunWizard';

const METHODS = [{id: 'dowser', name: 'Dowser'}] as unknown as MethodInfo[];
const window_ = (over = {}) => ({limit: 5, used: 0, remaining: 5, window_seconds: 3600, reset_at: null, retry_after_seconds: null, ...over});
const quota = (over: Partial<RunQuotaResponse> = {}): RunQuotaResponse => ({
  can_submit: true, blocked_by: null, message: null, retry_after_seconds: null,
  hourly: window_(), submissions: window_({limit: 30, remaining: 30}),
  queue: {max_queued: 5, queued_count: 0, unfinished: 0, can_add: true},
  server_time: new Date().toISOString(), ...over,
});
const BLOCKED = quota({
  can_submit: false, blocked_by: 'RUN_QUOTA_EXCEEDED', retry_after_seconds: 600,
  message: 'You have reached the limit of 5 runs per hour. You can start another run when the oldest of them is an hour old.',
  hourly: window_({used: 5, remaining: 0, reset_at: new Date(Date.now() + 600_000).toISOString(), retry_after_seconds: 600}),
});

async function openParametersStep(onSubmitDone = vi.fn()) {
  render(<RunWizard methods={METHODS} initialMethodId="dowser" onSubmitDone={onSubmitDone} />);
  fireEvent.click(screen.getByText('choose file'));
  await screen.findByText('submit run');
  return onSubmitDone;
}

beforeEach(() => {
  Object.values(mocks).forEach(m => typeof m === 'function' && m.mockReset());
  mocks.quota.current = quota({hourly: window_({used: 2, remaining: 3})});
  mocks.refetch.mockImplementation(async () => ({data: mocks.quota.current}));
  mocks.upload.mockResolvedValue({file_id: 'file-1'});
  mocks.create.mockResolvedValue({run_id: 'run-1', queued: false, queue_position: null});
});
afterEach(cleanup);

it('shows the allowance and lets a run through while the limit is not reached', async () => {
  const onSubmitDone = await openParametersStep();
  expect(screen.getByTestId('run-quota-usage').textContent).toBe('2 of 5 runs used this hour');
  expect(mocks.parametersProps.current?.runBlockedReason).toBeNull();
  await act(async () => { fireEvent.click(screen.getByText('submit run')); });
  await waitFor(() => expect(onSubmitDone).toHaveBeenCalledWith('run-1'));
  expect(mocks.upload).toHaveBeenCalledTimes(1);
  expect(mocks.create).toHaveBeenCalledWith({methodId: 'dowser', params: {seed: 1}, fileId: 'file-1'});
});

it('disables Run and explains why once the hourly limit is reached', async () => {
  mocks.quota.current = BLOCKED;
  await openParametersStep();
  expect(screen.getByRole('status').textContent).toContain('Hourly run limit reached');
  expect(screen.getByTestId('run-quota-countdown').textContent).toMatch(/^(10:0[01]|9:5\d)$/);
  expect(mocks.parametersProps.current?.runBlockedReason).toContain('limit of 5 runs per hour');
});

it('checks the limit again before uploading, so no file is sent for a run that would be refused', async () => {
  const onSubmitDone = await openParametersStep();
  // The allowance was used up elsewhere (another tab) after this form was opened.
  mocks.refetch.mockResolvedValue({data: BLOCKED});
  await act(async () => { fireEvent.click(screen.getByText('submit run')); });
  await waitFor(() => expect(mocks.notifyError).toHaveBeenCalledTimes(1));
  expect(mocks.notifyError.mock.calls[0][0]).toBe('Hourly run limit reached');
  expect(mocks.upload).not.toHaveBeenCalled();
  expect(mocks.create).not.toHaveBeenCalled();
  expect(onSubmitDone).not.toHaveBeenCalled();
});

it('a refusal by the server is explained once, not as a generic failure', async () => {
  const onSubmitDone = await openParametersStep();
  // Lost the race against another request: the server refuses with 429.
  mocks.create.mockRejectedValue({status: 'error', message: BLOCKED.message, data: {code: 'RUN_QUOTA_EXCEEDED'}});
  await act(async () => { fireEvent.click(screen.getByText('submit run')); });
  await waitFor(() => expect(mocks.create).toHaveBeenCalledTimes(1));
  expect(mocks.notifyError).not.toHaveBeenCalled();          // useCreateRun reports limit refusals itself
  expect(onSubmitDone).not.toHaveBeenCalled();
});

it('other failures are still reported as failures', async () => {
  await openParametersStep();
  mocks.create.mockRejectedValue(new Error('Method service unavailable'));
  await act(async () => { fireEvent.click(screen.getByText('submit run')); });
  await waitFor(() => expect(mocks.notifyError).toHaveBeenCalledWith('Run failed', 'Method service unavailable'));
});
