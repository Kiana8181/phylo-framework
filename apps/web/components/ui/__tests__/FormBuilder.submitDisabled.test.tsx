// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import FormBuilder from '../FormBuilder';

const schema = {type: 'object', properties: {seed: {type: 'integer', title: 'Seed', default: 1}}} as any;
afterEach(cleanup);

it('blocks submitting, with the reason, while leaving the fields editable', async () => {
  const onSubmit = vi.fn();
  render(<FormBuilder schema={schema} onSubmit={onSubmit} submitDisabled submitDisabledReason="Hourly run limit reached" />);
  const run = screen.getByRole('button', {name: 'Run'}) as HTMLButtonElement;
  expect(run.disabled).toBe(true);
  expect(run.title).toBe('Hourly run limit reached');
  fireEvent.click(run);
  fireEvent.submit(run.closest('form')!);
  await new Promise(r => setTimeout(r, 20));
  expect(onSubmit).not.toHaveBeenCalled();
  const inputs = screen.getAllByRole('spinbutton') as HTMLInputElement[];
  expect(inputs.length).toBeGreaterThan(0);
  expect(inputs.every(i => !i.disabled)).toBe(true);
});

it('submits normally when nothing blocks it', async () => {
  const onSubmit = vi.fn();
  render(<FormBuilder schema={schema} onSubmit={onSubmit} />);
  const run = screen.getByRole('button', {name: 'Run'}) as HTMLButtonElement;
  expect(run.disabled).toBe(false);
  expect(run.title).toBe('');
  fireEvent.click(run);
  await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
});
