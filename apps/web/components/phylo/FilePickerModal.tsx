"use client";

import FileInput from "@/components/common/FileInput";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { useDeleteFile, useFilesList } from "@/features/files/hooks";
import { notify } from "@/lib/notify";
import type { FileSummary } from "@phylo/contracts";
import { useEffect } from "react";
import { createPortal } from "react-dom";

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatQuota(bytes: number): string {
  const gb = bytes / (1024 ** 3);
  return `${gb.toFixed(1)} GB`;
}

export default function FilePickerModal({
  open,
  onClose,
  onSelectExisting,
  onUploadNew,
  accept,
}: {
  open: boolean;
  onClose: () => void;
  onSelectExisting: (fileId: string, display: { name: string; size: number }) => void;
  onUploadNew: (files: File[]) => void;
  accept?: string;
}) {
  const { data, isLoading, error } = useFilesList();
  const deleteFile = useDeleteFile();

  // Lock body scroll when modal is open
  useEffect(() => {
    if (open) {
      const originalOverflow = document.body.style.overflow;
      const originalPaddingRight = document.body.style.paddingRight;
      // Calculate scrollbar width to prevent layout shift
      const scrollbarWidth = window.innerWidth - document.documentElement.clientWidth;
      document.body.style.overflow = "hidden";
      if (scrollbarWidth > 0) {
        document.body.style.paddingRight = `${scrollbarWidth}px`;
      }
      return () => {
        document.body.style.overflow = originalOverflow;
        document.body.style.paddingRight = originalPaddingRight;
      };
    }
  }, [open]);

  const files = data?.files ?? [];
  const totalBytesUsed = data?.total_bytes_used ?? 0;
  const quotaBytes = data?.quota_bytes ?? 0;
  const atOrOverQuota = quotaBytes > 0 && totalBytesUsed >= quotaBytes;

  const handleDelete = async (file: FileSummary) => {
    try {
      await deleteFile.mutateAsync(file.id);
      notify.success("File deleted");
    } catch (e: unknown) {
      notify.error("Delete failed", (e as Error)?.message ?? "Unknown error");
    }
  };

  const handleUploadNew = (newFiles: File[]) => {
    if (newFiles.length) {
      onUploadNew(newFiles);
      onClose();
    }
  };

  const modalContent = (
    <>
      <div
        className="fixed inset-0 z-[100] bg-black/60 dark:bg-black/50 backdrop-blur-sm min-h-[100dvh] w-[100vw]"
        style={{ top: 0, left: 0, right: 0, bottom: 0 }}
        role="presentation"
        onClick={onClose}
        aria-hidden
      />
      <div className="fixed inset-0 z-[100] flex items-center justify-center p-4 pointer-events-none min-h-[100dvh]">
        <Card className="relative w-full max-w-lg max-h-[85vh] flex flex-col shadow-xl pointer-events-auto rounded-lg border bg-card text-card-foreground">
        <div className="p-4 border-b flex items-center justify-between">
          <h3 className="text-lg font-medium">Select or upload file</h3>
          <Button variant="ghost" size="sm" onClick={onClose} type="button">
            Close
          </Button>
        </div>
        <div className="p-4 overflow-y-auto space-y-4">
          {/* Quota */}
          <div className="text-sm text-muted-foreground">
            Used {formatBytes(totalBytesUsed)} / {formatQuota(quotaBytes)}
            {atOrOverQuota && (
              <span className="block text-amber-600 dark:text-amber-500 mt-1">
                Storage full. Delete files below or in File management to free space.
              </span>
            )}
          </div>

          {/* Your uploaded files */}
          <div>
            <h4 className="text-sm font-medium mb-2">Your uploaded files</h4>
            {isLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
            {error && (
              <p className="text-sm text-destructive">Failed to load files.</p>
            )}
            {!isLoading && !error && files.length === 0 && (
              <p className="text-sm text-muted-foreground">No files yet.</p>
            )}
            {!isLoading && !error && files.length > 0 && (
              <ul className="space-y-2">
                {files.map((file) => (
                  <li
                    key={file.id}
                    className="flex items-center justify-between gap-2 py-2 px-3 rounded-lg bg-muted/50 text-sm"
                  >
                    <div className="min-w-0 flex-1 truncate">
                      <span className="font-medium truncate block">{file.original_filename}</span>
                      <span className="text-muted-foreground">
                        {formatBytes(file.file_size)}
                        {file.uploaded_at && ` · ${new Date(file.uploaded_at).toLocaleDateString()}`}
                      </span>
                    </div>
                    <div className="flex gap-1 shrink-0">
                      <Button
                        variant="default"
                        size="sm"
                        type="button"
                        onClick={() => {
                          onSelectExisting(file.id, {
                            name: file.original_filename,
                            size: file.file_size,
                          });
                          onClose();
                        }}
                      >
                        Use
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        type="button"
                        onClick={() => handleDelete(file)}
                        disabled={deleteFile.isPending}
                      >
                        Delete
                      </Button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Upload new */}
          <div>
            <h4 className="text-sm font-medium mb-2">Upload new</h4>
            {atOrOverQuota ? (
              <p className="text-sm text-muted-foreground">
                Free space by deleting files above or in File management.
              </p>
            ) : (
              <div className="rounded-xl border-2 border-dashed bg-muted/20 p-4">
                <FileInput
                  accept={accept}
                  multiple={false}
                  onFiles={handleUploadNew}
                  disabled={atOrOverQuota}
                />
                <p className="text-xs text-muted-foreground mt-2">
                  Choose a file to upload and use for this run.
                </p>
              </div>
            )}
          </div>
        </div>
      </Card>
      </div>
    </>
  );

  if (!open) return null;

  if (typeof document !== "undefined") {
    return createPortal(modalContent, document.body);
  }
  return modalContent;
}
