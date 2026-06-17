import { serviceHandler, Method } from "@/lib/http/serviceHandler";
import { uploadWithProgress, type AbortableUpload } from "@/lib/utils";
import {
  API_ROUTES,
  type UploadInitResponse,
  type UploadedFileResponse,
} from "@phylo/contracts";

export const UploadsApi = {
  async init(input: {
    original_filename: string;
    mime_type?: string | null;
    expected_size?: number | null;
  }): Promise<UploadInitResponse> {
    return serviceHandler<UploadInitResponse>({
      method: Method.Post,
      url: API_ROUTES.uploadInit(),
      data: input,
    });
  },

  /** Upload the file body with progress + cancellation. */
  content(uploadId: string, file: File, onProgress: (pct: number) => void): AbortableUpload<UploadedFileResponse> {
    return uploadWithProgress<UploadedFileResponse>(
      API_ROUTES.uploadContent(uploadId),
      file,
      onProgress,
    );
  },

  async cancel(uploadId: string): Promise<void> {
    await serviceHandler<void>({
      method: Method.Delete,
      url: API_ROUTES.uploadCancel(uploadId),
      // Cancellation is idempotent; allow repeated calls.
      allowDuplicateRequests: true,
    });
  },
};
