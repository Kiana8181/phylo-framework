// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import ConfirmDialog from '../ConfirmDialog';
afterEach(cleanup);
it('confirms, cancels with Escape, restores scroll and removes listeners on unmount', () => {
  const close = vi.fn(), confirm = vi.fn();
  document.body.style.overflow = 'auto';
  const view = render(<ConfirmDialog open onOpenChange={close} title="Delete dataset" onConfirm={confirm} />);
  expect(screen.getByRole('alertdialog').getAttribute('aria-modal')).toBe('true');
  expect(document.body.style.overflow).toBe('hidden');
  fireEvent.click(screen.getByRole('button', {name: 'Confirm'}));
  expect(confirm).toHaveBeenCalledOnce();
  fireEvent.keyDown(document, {key: 'Escape'});
  expect(close).toHaveBeenCalledWith(false);
  view.unmount();
  expect(document.body.style.overflow).toBe('auto');
  close.mockClear();
  fireEvent.keyDown(document, {key: 'Escape'});
  expect(close).not.toHaveBeenCalled();
});
it('blocks duplicate confirmations and cancellation while pending', () => {
  const confirm = vi.fn(), close = vi.fn();
  render(<ConfirmDialog open pending onOpenChange={close} title="Delete" onConfirm={confirm} />);
  fireEvent.click(screen.getByRole('button', {name: 'Confirm'}));
  fireEvent.click(screen.getByRole('button', {name: 'Cancel'}));
  fireEvent.keyDown(document, {key: 'Escape'});
  expect(confirm).not.toHaveBeenCalled();
  expect(close).not.toHaveBeenCalled();
});
it('renders nothing when closed', () => {
  render(<ConfirmDialog open={false} onOpenChange={vi.fn()} title="Delete" onConfirm={vi.fn()} />);
  expect(screen.queryByRole('alertdialog')).toBeNull();
});
