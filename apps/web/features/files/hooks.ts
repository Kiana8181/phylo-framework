import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { FilesApi, type FastaIdStyleResponse } from "./api";
import type { FilesListResponse } from "@phylo/contracts";

export const FILES_LIST_QUERY_KEY = ["filesList"] as const;
export const FASTA_ID_STYLE_QUERY_KEY = ["fastaIdStyle"] as const;

/** Headers of an already-uploaded FASTA never change, so cache indefinitely. */
export function useFastaIdStyle(fileId: string | undefined, opts?: { enabled?: boolean }) {
  return useQuery<FastaIdStyleResponse>({
    queryKey: [...FASTA_ID_STYLE_QUERY_KEY, fileId],
    queryFn: () => FilesApi.fastaIdStyle(fileId as string),
    enabled: Boolean(fileId) && (opts?.enabled ?? true),
    staleTime: Infinity,
  });
}

export function useFilesList(opts?: { skip?: number; limit?: number }) {
  return useQuery<FilesListResponse>({
    queryKey: [...FILES_LIST_QUERY_KEY, opts?.skip ?? 0, opts?.limit ?? 100],
    queryFn: () => FilesApi.list(opts),
  });
}

export function useDeleteFile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => FilesApi.deleteFile(id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: FILES_LIST_QUERY_KEY });
    },
  });
}
