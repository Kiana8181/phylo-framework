// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen, waitFor} from '@testing-library/react';
import {afterEach, expect, it} from 'vitest';
import type {FileSummary} from '@phylo/contracts';
import DatasetExpirationNotice from '../DatasetExpirationNotice';

afterEach(() => {
  cleanup();
  sessionStorage.clear();
});

function dataset(id: string, name: string): FileSummary {
  return {
    id,
    original_filename: name,
    file_size: 12,
    uploaded_at: '2026-01-01T00:00:00Z',
    run_id: null,
    expires_at: '2026-12-01T15:00:00Z',
    renewal_eligible: true,
  };
}

it('shows nothing when the backend reports no approaching datasets', () => {
  const {container} = render(<DatasetExpirationNotice datasets={[]} />);
  expect(container.innerHTML).toBe('');
});

it('names each dataset, its expiration, and the way to renew it', () => {
  render(<DatasetExpirationNotice datasets={[dataset('a', 'alpha.tsv'), dataset('b', 'beta.tsv')]} />);
  const notice = screen.getByTestId('dataset-expiration');
  expect(notice.textContent).toContain('Your dataset alpha.tsv is approaching its expiration date');
  expect(notice.textContent).toContain('beta.tsv');
  expect(notice.textContent).toContain('will be automatically deleted soon');
  expect(notice.textContent).toContain('visit File Management to renew it');
  expect(screen.getByRole('link', {name: 'File management'}).getAttribute('href')).toBe('/dashboard/files');
});

it('stays hidden for the rest of the session and returns for a new dataset', async () => {
  const first = [dataset('a', 'alpha.tsv')];
  render(<DatasetExpirationNotice datasets={first} />);
  fireEvent.click(screen.getByRole('button', {name: 'Dismiss'}));
  expect(screen.queryByTestId('dataset-expiration')).toBeNull();

  cleanup();
  render(<DatasetExpirationNotice datasets={first} />);
  await waitFor(() => expect(screen.queryByTestId('dataset-expiration')).toBeNull());

  cleanup();
  render(<DatasetExpirationNotice datasets={[...first, dataset('b', 'beta.tsv')]} />);
  expect(screen.getByTestId('dataset-expiration').textContent).toContain('beta.tsv');
});
