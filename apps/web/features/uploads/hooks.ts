import { useCallback, useRef, useState } from "react";
import { UploadsApi } from "./api";
import type { UploadedFileResponse } from "@phylo/contracts";

type UploadState = {
  uploading: boolean;
  progress: number | null;
  uploadId: string | null;
};

/**
 * Manages a single cancellable upload session lifecycle:
 *   init -> stream content (with progress + abort) -> completed file_id.
 * Calling cancel() aborts the in-flight browser request and tells the server
 * to clean up the partial/temporary data.
 */
export function useUploadSession() {
  const [state, setState] = useState<UploadState>({
    uploading: false,
    progress: null,
    uploadId: null,
  });
  const abortRef = useRef<(() => void) | null>(null);
  const uploadIdRef = useRef<string | null>(null);

  const reset = useCallback(() => {
    abortRef.current = null;
    uploadIdRef.current = null;
    setState({ uploading: false, progress: null, uploadId: null });
  }, []);

  const upload = useCallback(async (file: File): Promise<UploadedFileResponse> => {
    const init = await UploadsApi.init({
      original_filename: file.name,
      mime_type: file.type || null,
      expected_size: file.size,
    });
    uploadIdRef.current = init.upload_id;
    setState({ uploading: true, progress: 0, uploadId: init.upload_id });

    const { promise, abort } = UploadsApi.content(init.upload_id, file, (pct) =>
      setState((s) => ({ ...s, progress: pct })),
    );
    abortRef.current = abort;

    try {
      const result = await promise;
      setState({ uploading: false, progress: 100, uploadId: null });
      abortRef.current = null;
      uploadIdRef.current = null;
      return result;
    } catch (err) {
      // On any failure (including abort), make a best-effort cleanup call.
      const id = uploadIdRef.current;
      abortRef.current = null;
      uploadIdRef.current = null;
      setState({ uploading: false, progress: null, uploadId: null });
      if (id) {
        try {
          await UploadsApi.cancel(id);
        } catch {
          /* idempotent best-effort */
        }
      }
      throw err;
    }
  }, []);

  const cancel = useCallback(async () => {
    if (abortRef.current) {
      abortRef.current();
      abortRef.current = null;
    }
    const id = uploadIdRef.current;
    uploadIdRef.current = null;
    setState({ uploading: false, progress: null, uploadId: null });
    if (id) {
      try {
        await UploadsApi.cancel(id);
      } catch {
        /* idempotent best-effort */
      }
    }
  }, []);

  return { ...state, upload, cancel, reset };
}
