import { API_ROUTES } from "@phylo/contracts";
import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import type { FilesListResponse } from "@phylo/contracts";
import type { FastaIdStyle } from "@/lib/fastaIdStyle";

export type FastaIdStyleResponse = {
  style: FastaIdStyle;
  headers_checked: number;
  truncated: boolean;
};

export const FilesApi = {
  async list(opts?: { skip?: number; limit?: number }): Promise<FilesListResponse> {
    return serviceHandler<FilesListResponse>({
      method: Method.Get,
      url: API_ROUTES.filesList(),
      params: { skip: opts?.skip ?? 0, limit: opts?.limit ?? 100 },
    });
  },

  /** Peek at an already-uploaded FASTA's headers (see lib/fastaIdStyle.ts). */
  async fastaIdStyle(id: string): Promise<FastaIdStyleResponse> {
    return serviceHandler<FastaIdStyleResponse>({
      method: Method.Get,
      url: API_ROUTES.datasetFastaIdStyle(id),
    });
  },

  async deleteFile(id: string): Promise<void> {
    await serviceHandler<void>({
      method: Method.Delete,
      url: API_ROUTES.filesDelete(id),
    });
  },
};
