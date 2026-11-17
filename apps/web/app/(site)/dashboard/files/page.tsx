"use client";

import ConfirmDialog from "@/components/common/ConfirmDialog";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import {
  ResponsiveTable,
  ResponsiveTableBody,
  ResponsiveTableCell,
  ResponsiveTableHeader,
  ResponsiveTableRow,
} from "@/components/ui/responsive-table";
import { useDeleteFile, useFilesList, useRenewFile } from "@/features/files/hooks";
import { notify } from "@/lib/notify";
import { Trash2 } from "lucide-react";
import { Loading } from "@/components/ui/loading";
import { useState } from "react";

type PendingDelete = {
  id: string;
  name: string;
};

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
  const renewFile = useRenewFile();
  const [pendingDelete, setPendingDelete] = useState<PendingDelete | null>(null);

  const files = data?.files ?? [];
  const totalBytesUsed = data?.total_bytes_used ?? 0;
  const quotaBytes = data?.quota_bytes ?? 0;
  const quotaPct = quotaBytes > 0 ? Math.min(100, (totalBytesUsed / quotaBytes) * 100) : 0;

  const handleRenew = async (id: string, name: string) => {
    try {
      await renewFile.mutateAsync(id);
      notify.success("Dataset renewed", `${name} has a new expiration date.`);
    } catch (e: unknown) {
      notify.error("Renewal failed", (e as Error)?.message ?? "Unknown error");
    }
  };

  const handleConfirmDelete = async () => {
    if (!pendingDelete) return;
    try {
      await deleteFile.mutateAsync(pendingDelete.id);
      notify.success("Dataset deleted");
      setPendingDelete(null);
    } catch (e: unknown) {
      notify.error("Delete failed", (e as Error)?.message ?? "Unknown error");
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
            <ResponsiveTable stackBelow="md" labelPlacement="side">
              <ResponsiveTableHeader
                columns={[
                  "Name",
                  "Size",
                  "Uploaded",
                  "Expires",
                  "Run ID",
                  { label: "Actions", className: "w-40 text-right" },
                ]}
              />
              <ResponsiveTableBody>
                {files.map((file) => {
                  const renewing = renewFile.isPending && renewFile.variables === file.id;
                  return (
                  <ResponsiveTableRow
                    key={file.id}
                    className={file.renewal_eligible ? "bg-amber-50/80 dark:bg-amber-950/20" : undefined}
                  >
                    <ResponsiveTableCell label="Name" className="font-medium">
                      <span className="block @2xl:max-w-[12rem] @2xl:truncate" title={file.original_filename}>
                        {file.original_filename}
                      </span>
                    </ResponsiveTableCell>
                    <ResponsiveTableCell label="Size" className="text-muted-foreground">
                      {formatSize(file.file_size)}
                    </ResponsiveTableCell>
                    <ResponsiveTableCell label="Uploaded" className="text-muted-foreground">
                      {formatDate(file.uploaded_at)}
                    </ResponsiveTableCell>
                    <ResponsiveTableCell label="Expires" className="text-muted-foreground">
                      <span className={file.renewal_eligible ? "font-medium text-amber-800 dark:text-amber-200" : undefined}>
                        {file.expires_at ? formatDate(file.expires_at ?? null) : "—"}
                      </span>
                      {file.renewal_eligible && (
                        <span className="mt-0.5 block text-xs text-amber-700 dark:text-amber-300">Expires soon</span>
                      )}
                    </ResponsiveTableCell>
                    <ResponsiveTableCell label="Run ID" className="font-mono text-xs">
                      <span className="block @2xl:max-w-[8rem] @2xl:truncate">{file.run_id ?? "—"}</span>
                    </ResponsiveTableCell>
                    <ResponsiveTableCell className="text-right">
                      <div className="flex flex-wrap items-center justify-end gap-2">
                        {file.renewal_eligible && (
                          <Button
                            variant="outline"
                            size="sm"
                            onClick={() => handleRenew(file.id, file.original_filename)}
                            disabled={renewFile.isPending || deleteFile.isPending}
                            aria-label={`Renew ${file.original_filename}`}
                          >
                            {renewing ? "Renewing…" : "Renew"}
                          </Button>
                        )}
                        <Button
                          variant="outline"
                          size="sm"
                          className="text-destructive hover:text-destructive"
                          onClick={() =>
                            setPendingDelete({
                              id: file.id,
                              name: file.original_filename,
                            })
                          }
                          disabled={deleteFile.isPending || renewFile.isPending}
                          aria-label={`Delete ${file.original_filename}`}
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </div>
                    </ResponsiveTableCell>
                  </ResponsiveTableRow>
                  );
                })}
              </ResponsiveTableBody>
            </ResponsiveTable>
          )}
        </CardContent>
      </Card>

      <ConfirmDialog
        open={pendingDelete !== null}
        onOpenChange={(open) => {
          if (!open && !deleteFile.isPending) setPendingDelete(null);
        }}
        title="Delete dataset?"
        description={
          pendingDelete ? (
            <>
              <span className="font-medium text-foreground">{pendingDelete.name}</span> will be
              permanently removed. Past runs that used this dataset will keep their results, but
              you won&apos;t be able to rerun them with this file.
            </>
          ) : null
        }
        confirmLabel="Delete dataset"
        cancelLabel="Cancel"
        destructive
        pending={deleteFile.isPending}
        onConfirm={handleConfirmDelete}
      />
    </main>
  );
}
