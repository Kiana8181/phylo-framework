"use client";

import FileInput from "@/components/common/FileInput";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";
import { Label } from "@/components/ui/label";
import { useCreateRun } from "@/features/runs/hooks";
import { notify } from "@/lib/notify";
import type { MethodSpec } from "@phylo/contracts";
import { useMemo, useState } from "react";
import FilePickerModal from "./FilePickerModal";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function RunParameters({
  spec,
  files,
  onFiles,
  onSubmitDone,
  runInProgress = false,
}: {
  spec: MethodSpec;
  files: File[];
  onFiles: (files: File[]) => void;
  onSubmitDone?: (runId: string) => void;
  runInProgress?: boolean;
}) {
  const createRun = useCreateRun();
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [filePickerOpen, setFilePickerOpen] = useState(false);
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null);
  const [selectedFileDisplay, setSelectedFileDisplay] = useState<{ name: string; size: number } | null>(null);

  const requiresFile =
    spec.uiHints?.requiresFile === true || (spec?.accepts?.length ?? 0) > 0;
  const hasFile = !!(selectedFileId || (files?.length ?? 0) > 0);
  const canSubmit = !requiresFile || hasFile;

  const schemaMemo = useMemo(
    () => ({ ...(spec.paramSchema ?? {}), uiHints: spec.uiHints }),
    [spec.id, spec.paramSchema, spec.uiHints]
  );

  async function handleSubmit(values: Record<string, any>) {
    const fd = new FormData();
    fd.set("params", JSON.stringify(values ?? {}));

    if (selectedFileId) {
      fd.set("file_id", selectedFileId);
    } else {
      const maxFiles = Number(spec.uiHints?.maxFiles ?? 1);
      if (files?.length) {
        if (maxFiles <= 1) {
          const f = files[0];
          fd.set("file", f, f.name);
        } else {
          files.forEach((f) => fd.append("file", f, f.name));
        }
      }
    }

    setUploadPct(0);
    try {
      const res = await createRun.mutateAsync({
        methodId: spec.id,
        formData: fd,
        onProgress: (pct) => setUploadPct(pct),
      });
      setUploadPct(null);
      onSubmitDone?.(res.run_id);
    } catch (e: any) {
      setUploadPct(null);
      notify.error("Run failed", e?.message ?? "Unknown error");
    }
  }

  return (
    <Card className="p-4 space-y-4">
      <div>
        <h3 className="text-lg font-medium">{spec.name} parameters</h3>
        <p className="text-xs text-muted-foreground">
          Configure inputs for this method
        </p>
      </div>

      {requiresFile && !hasFile && (
        <p className="text-sm text-amber-600 dark:text-amber-500">
          Select or upload a file to run this method.
        </p>
      )}

      <FormBuilder
        schema={schemaMemo}
        onSubmit={handleSubmit}
        disabled={runInProgress || (requiresFile && !hasFile)}
        footer={
          <div className="col-span-full">
            <div className="flex items-center justify-between mb-2">
              <div>
                <Label className="text-sm">Input files</Label>
                <p className="text-xs text-muted-foreground">
                  Accepted: {(spec?.accepts ?? []).join(", ") || "—"}
                </p>
              </div>
              <Button
                variant="outline"
                onClick={() => {
                  setSelectedFileId(null);
                  setSelectedFileDisplay(null);
                  onFiles([]);
                }}
                disabled={(!selectedFileId && !files?.length) || runInProgress}
                type="button"
              >
                Clear
              </Button>
            </div>

            <div className="rounded-2xl border-2 border-dashed bg-muted/30 p-6 space-y-3">
              <div className="flex flex-wrap gap-2 items-center">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setFilePickerOpen(true)}
                  disabled={runInProgress}
                >
                  Select file
                </Button>
                <span className="text-xs text-muted-foreground">or upload:</span>
                <FileInput
                  accept={(spec?.accepts ?? []).join(",")}
                  multiple={(spec?.uiHints?.maxFiles ?? 1) > 1}
                  onFiles={(newFiles) => {
                    setSelectedFileId(null);
                    setSelectedFileDisplay(null);
                    onFiles(newFiles);
                  }}
                  disabled={runInProgress}
                />
              </div>
              <FilePickerModal
                open={filePickerOpen}
                onClose={() => setFilePickerOpen(false)}
                onSelectExisting={(fileId, display) => {
                  setSelectedFileId(fileId);
                  setSelectedFileDisplay(display);
                  onFiles([]);
                }}
                onUploadNew={(newFiles) => {
                  setSelectedFileId(null);
                  setSelectedFileDisplay(null);
                  onFiles(newFiles);
                }}
                accept={(spec?.accepts ?? []).join(",")}
              />
              <div className="mt-3">
                {selectedFileId && selectedFileDisplay ? (
                  <p className="text-sm">
                    Using: <span className="font-medium">{selectedFileDisplay.name}</span>{" "}
                    ({formatSize(selectedFileDisplay.size)})
                  </p>
                ) : files?.length ? (
                  <ul className="space-y-1 text-sm">
                    {files.map((f, i) => (
                      <li key={i} className="truncate">
                        • {f.name}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    No file selected. Click &quot;Select file&quot; to choose an existing file or upload a new one.
                  </p>
                )}
              </div>
            </div>
          </div>
        }
      />

      {uploadPct !== null && (
        <div className="space-y-2">
          <div className="text-sm">
            Uploading{Number.isFinite(uploadPct) ? ` (${uploadPct}%)` : ""}
          </div>
          <div className="h-2 w-full bg-muted rounded overflow-hidden">
            <div
              className="h-full rounded bg-primary transition-[width]"
              style={{ width: `${uploadPct ?? 0}%` }}
            />
          </div>
        </div>
      )}
    </Card>
  );
}
