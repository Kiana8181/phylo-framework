// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';
import RunProgress from '../RunProgress';
const {cancel} = vi.hoisted(() => ({cancel: vi.fn()}));
vi.mock('@/features/runs/hooks', () => ({useCancelRun: () => ({mutateAsync: cancel, isPending: false})}));
vi.mock('@/lib/notify', () => ({notify: {success: vi.fn()}}));
afterEach(cleanup);
beforeEach(() => {cancel.mockReset(); cancel.mockResolvedValue({});});
it('stops the selected active run and disables stopping after cancellation requested', async () => {
  const view = render(<RunProgress runId="r1" status="RUNNING" progress={30} stage="BUILDING_TREES" />);
  fireEvent.click(screen.getByRole('button', {name: /stop/i}));
  await waitFor(() => expect(cancel).toHaveBeenCalledWith('r1'));
  view.rerender(<RunProgress runId="r1" status="RUNNING" progress={30} stage="CANCELLING" />);
  expect(screen.queryByRole('button', {name: /^stop/i})).toBeNull();
});
it.each(['DONE', 'ERROR', 'CANCELLED'])('terminal status %s cannot be stopped', status => {
  render(<RunProgress runId="r1" status={status} progress={100} />);
  expect(screen.queryByRole('button', {name: /stop/i})).toBeNull();
});
it('shows access error without presenting fake progress', () => {
  render(<RunProgress runId="r1" progress={0} statusError={{response: {status: 403}}} />);
  expect(screen.getByText(/don't have access/)).toBeTruthy();
});
