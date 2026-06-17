"use client";

import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { useDeleteFile, useFilesList } from "@/features/files/hooks";
import { notify } from "@/lib/notify";
import { Trash2 } from "lucide-react";
import { Loading, Spinner } from "@/components/ui/loading";
import { useState } from "react";

function formatDate(iso: string | null) {
  if (!iso) return "—";
  try {
    const d = new Date(iso);
    return d.toLocaleString();
  } catch {
    return iso;
  }
}

function formatSize(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function formatQuota(bytes: number): string {
  const gb = bytes / 1024 ** 3;
  return `${gb.toFixed(1)} GB`;
}

export default function FileManagementPage() {
  const { data, isLoading, error } = useFilesList();
  const deleteFile = useDeleteFile();
  const [deletingId, setDeletingId] = useState<string | null>(null);

  const files = data?.files ?? [];
  const totalBytesUsed = data?.total_bytes_used ?? 0;
  const quotaBytes = data?.quota_bytes ?? 0;
  const quotaPct = quotaBytes > 0 ? Math.min(100, (totalBytesUsed / quotaBytes) * 100) : 0;

  const handleDelete = async (id: string, name: string) => {
    if (!confirm(`Delete "${name}"? This cannot be undone.`)) return;
    setDeletingId(id);
    try {
      await deleteFile.mutateAsync(id);
      notify.success("File deleted");
    } catch (e: unknown) {
      notify.error("Delete failed", (e as Error)?.message ?? "Unknown error");
    } finally {
      setDeletingId(null);
    }
  };

  return (
    <main className="mx-auto max-w-5xl w-full p-4 sm:p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          File management
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          View and manage files uploaded with your runs.
        </p>
      </header>

      {!isLoading && !error && quotaBytes > 0 && (
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-base">Storage</CardTitle>
            <CardDescription>
              Used {formatSize(totalBytesUsed)} / {formatQuota(quotaBytes)}
            </CardDescription>
          </CardHeader>
          <CardContent className="pt-0">
            <Progress value={quotaPct} className="h-2" />
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <CardTitle>Files</CardTitle>
          <CardDescription>Files associated with your runs.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && <Loading label="Loading files…" />}
          {error && (
            <p className="text-destructive text-sm py-4">
              Failed to load files. Please try again.
            </p>
          )}
          {!isLoading && !error && files.length === 0 && (
            <p className="text-muted-foreground text-sm py-8 text-center">
              No files yet. Upload a file when starting a run.
            </p>
          )}
          {!isLoading && !error && files.length > 0 && (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="text-left py-3 px-2 font-medium">Name</th>
                    <th className="text-left py-3 px-2 font-medium">Size</th>
                    <th className="text-left py-3 px-2 font-medium">Uploaded</th>
                    <th className="text-left py-3 px-2 font-medium">Run ID</th>
                    <th className="text-right py-3 px-2 font-medium w-24">Actions</th>
                  </tr>
                </thead>
                <tbody>
                  {files.map((file) => (
                    <tr key={file.id} className="border-b last:border-0">
                      <td className="py-3 px-2 font-medium truncate max-w-[12rem]">
                        {file.original_filename}
                      </td>
                      <td className="py-3 px-2 text-muted-foreground">
                        {formatSize(file.file_size)}
                      </td>
                      <td className="py-3 px-2 text-muted-foreground">
                        {formatDate(file.uploaded_at)}
                      </td>
                      <td className="py-3 px-2 font-mono text-xs truncate max-w-[8rem]">
                        {file.run_id ?? "—"}
                      </td>
                      <td className="py-3 px-2 text-right">
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() => handleDelete(file.id, file.original_filename)}
                          disabled={deletingId === file.id || deleteFile.isPending}
                        >
                          {deletingId === file.id ? (
                            <Spinner />
                          ) : (
                            <Trash2 className="h-4 w-4" />
                          )}
                        </Button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </main>
  );
}
