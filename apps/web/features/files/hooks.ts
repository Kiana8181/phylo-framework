import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useQuery } from "@tanstack/react-query";
import { FilesApi } from "./api";
import type { FilesListResponse } from "@phylo/contracts";

export const FILES_LIST_QUERY_KEY = ["filesList"] as const;

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
