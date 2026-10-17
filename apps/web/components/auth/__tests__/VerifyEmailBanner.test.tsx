// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, beforeEach, expect, it, vi} from 'vitest';

const mocks = vi.hoisted(() => ({
  user: {current: null as null | Record<string, unknown>},
  refreshUser: vi.fn(),
  resend: vi.fn(),
  success: vi.fn(),
  error: vi.fn(),
}));
vi.mock('@/features/auth/context', () => ({useAuth: () => ({user: mocks.user.current, refreshUser: mocks.refreshUser})}));
vi.mock('@/features/auth/api', () => ({authApi: {resendVerification: mocks.resend}}));
vi.mock('@/lib/notify', () => ({notify: {success: mocks.success, error: mocks.error}}));

import VerifyEmailBanner from '../VerifyEmailBanner';
import {needsEmailVerification} from '@/lib/auth/storage';

const ADA = {id: '1', email: 'ada@uni.example', username: 'ada'};
beforeEach(() => { Object.values(mocks).forEach(m => typeof m === 'function' && m.mockReset()); });
afterEach(cleanup);

it.each([
  [null, false],
  [ADA, false],                                                      // older session without the fields
  [{...ADA, email_verified: true, verification_required: true}, false],
  [{...ADA, email_verified: false, verification_required: false}, false],   // this deployment does not ask
  [{...ADA, email_verified: false, verification_required: true}, true],
])('needsEmailVerification(%j) is %s', (user, expected) => {
  expect(needsEmailVerification(user as never)).toBe(expected);
});

it('is not shown to a confirmed account or where confirmation is not required', () => {
  mocks.user.current = {...ADA, email_verified: true, verification_required: true};
  const {container, rerender} = render(<VerifyEmailBanner />);
  expect(container.innerHTML).toBe('');
  mocks.user.current = {...ADA, email_verified: false, verification_required: false};
  rerender(<VerifyEmailBanner />);
  expect(container.innerHTML).toBe('');
});

it('tells an unconfirmed account what to do and sends a new link on request', async () => {
  mocks.user.current = {...ADA, email_verified: false, verification_required: true};
  mocks.resend.mockResolvedValue({email_verified: false, message: 'We sent a new confirmation link to ada@uni.example.'});
  render(<VerifyEmailBanner />);
  const banner = screen.getByTestId('verify-email-banner');
  expect(banner.textContent).toContain('Confirm your email address to upload data and start runs.');
  expect(banner.textContent).toContain('ada@uni.example');
  fireEvent.click(screen.getByRole('button', {name: 'Send a new link'}));
  await waitFor(() => expect(mocks.success).toHaveBeenCalledWith('We sent a new confirmation link to ada@uni.example.'));
  expect(mocks.resend).toHaveBeenCalledTimes(1);
  expect(mocks.refreshUser).not.toHaveBeenCalled();
});

it('notices when the address was confirmed in the meantime', async () => {
  mocks.user.current = {...ADA, email_verified: false, verification_required: true};
  mocks.resend.mockResolvedValue({email_verified: true, message: 'Your email address is already confirmed.'});
  render(<VerifyEmailBanner />);
  fireEvent.click(screen.getByRole('button', {name: 'Send a new link'}));
  await waitFor(() => expect(mocks.refreshUser).toHaveBeenCalledTimes(1));
});

it('reports a refused request (for example too many) without breaking', async () => {
  mocks.user.current = {...ADA, email_verified: false, verification_required: true};
  mocks.resend.mockRejectedValue({response: {data: {status: 'error', message: 'Too many attempts. Please wait and try again.'}}});
  render(<VerifyEmailBanner />);
  fireEvent.click(screen.getByRole('button', {name: 'Send a new link'}));
  await waitFor(() => expect(mocks.error).toHaveBeenCalledWith('Could not send the email', 'Too many attempts. Please wait and try again.'));
  expect((screen.getByRole('button', {name: 'Send a new link'}) as HTMLButtonElement).disabled).toBe(false);
});
