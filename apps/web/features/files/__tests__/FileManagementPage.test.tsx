// @vitest-environment jsdom
import {cleanup, fireEvent, render, screen} from '@testing-library/react';
import {afterEach, expect, it, vi} from 'vitest';
import type {FileSummary} from '@phylo/contracts';

const renew = vi.fn().mockResolvedValue({});

vi.mock('@/lib/notify', () => ({notify: {success: vi.fn(), error: vi.fn()}}));
vi.mock('@/features/files/hooks', () => ({
  useFilesList: vi.fn(),
  useDeleteFile: vi.fn(),
  useRenewFile: vi.fn(),
}));

import {useDeleteFile, useFilesList, useRenewFile} from '@/features/files/hooks';
import FileManagementPage from '@/app/(site)/dashboard/files/page';

afterEach(() => {
  cleanup();
  renew.mockClear();
});

function file(partial: Partial<FileSummary> & Pick<FileSummary, 'id' | 'original_filename'>): FileSummary {
  return {
    file_size: 2048,
    uploaded_at: '2026-01-02T00:00:00Z',
    run_id: null,
    expires_at: '2026-06-01T00:00:00Z',
    renewal_eligible: false,
    ...partial,
  };
}

it('shows the backend expiration and offers renewal only when the backend says so', () => {
  vi.mocked(useFilesList).mockReturnValue({
    data: {
      files: [
        file({id: 'soon', original_filename: 'soon.tsv', renewal_eligible: true, expires_at: '2026-04-01T00:00:00Z'}),
        file({id: 'later', original_filename: 'later.tsv', renewal_eligible: false}),
      ],
      approaching: [],
      total_bytes_used: 4096,
      quota_bytes: 1024 ** 3,
    },
    isLoading: false,
    error: null,
  } as ReturnType<typeof useFilesList>);
  vi.mocked(useDeleteFile).mockReturnValue({mutateAsync: vi.fn(), isPending: false} as unknown as ReturnType<typeof useDeleteFile>);
  vi.mocked(useRenewFile).mockReturnValue({
    mutateAsync: renew,
    isPending: false,
    variables: undefined,
  } as unknown as ReturnType<typeof useRenewFile>);

  render(<FileManagementPage />);

  expect(screen.getByText('soon.tsv')).toBeTruthy();
  expect(screen.getByText('Expires soon')).toBeTruthy();
  expect(screen.getAllByRole('button', {name: 'Renew soon.tsv'})).toHaveLength(1);
  expect(screen.queryByRole('button', {name: 'Renew later.tsv'})).toBeNull();

  fireEvent.click(screen.getByRole('button', {name: 'Renew soon.tsv'}));
  expect(renew).toHaveBeenCalledWith('soon');
});
