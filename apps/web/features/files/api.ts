import { API_ROUTES } from "@phylo/contracts";
import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import type { FilesListResponse } from "@phylo/contracts";

export const FilesApi = {
  async list(opts?: { skip?: number; limit?: number }): Promise<FilesListResponse> {
    return serviceHandler<FilesListResponse>({
      method: Method.Get,
      url: API_ROUTES.filesList(),
      params: { skip: opts?.skip ?? 0, limit: opts?.limit ?? 100 },
    });
  },

  async deleteFile(id: string): Promise<void> {
    await serviceHandler<void>({
      method: Method.Delete,
      url: API_ROUTES.filesDelete(id),
    });
  },
};
