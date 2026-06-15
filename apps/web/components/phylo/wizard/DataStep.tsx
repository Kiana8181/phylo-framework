"use client";

import Link from "next/link";
import { useMemo } from "react";
import { ArrowLeft, FolderCog } from "lucide-react";
import FileInput from "@/components/common/FileInput";
import { Button } from "@/components/ui/button";
import { Loading } from "@/components/ui/loading";
import { useFilesList } from "@/features/files/hooks";
import { acceptAttr, isFileCompatible } from "@/lib/fileTypes";
import type { MethodSpec } from "@phylo/contracts";
import type { ChosenInput } from "./types";

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export default function DataStep({
  spec,
  onChoose,
  onBack,
}: {
  spec: MethodSpec;
  onChoose: (input: ChosenInput) => void;
  onBack: () => void;
}) {
  const { data, isLoading, error } = useFilesList();

  const uploadGuidance = Array.isArray(spec.uiHints?.uploadGuidance)
    ? (spec.uiHints?.uploadGuidance as string[])
    : [];
  const fileLabel =
    typeof spec.uiHints?.fileLabel === "string" ? spec.uiHints.fileLabel : "Input dataset";

  const compatibleFiles = useMemo(
    () => (data?.files ?? []).filter((file) => isFileCompatible(file, spec.accepts)),
    [data?.files, spec.accepts],
  );

  return (
    <div className="space-y-6">
      <div className="space-y-1">
        <h3 className="text-lg font-medium">{fileLabel}</h3>
        <p className="text-xs text-muted-foreground">
          Accepted: {(spec.accepts ?? []).join(", ") || "—"}
        </p>
        {uploadGuidance.length > 0 && (
          <div className="mt-2 space-y-1 text-xs text-muted-foreground">
            {uploadGuidance.map((line, idx) => (
              <p key={`${spec.id}-guidance-${idx}`}>{line}</p>
            ))}
          </div>
        )}
      </div>

      <div className="rounded-2xl border-2 border-dashed bg-muted/30 p-6">
        <p className="mb-2 text-sm font-medium">Upload a new file</p>
        <FileInput
          accept={acceptAttr(spec.accepts)}
          multiple={false}
          onFiles={(files) => {
            if (files.length > 0) onChoose({ kind: "upload", file: files[0] });
          }}
        />
        <p className="mt-2 text-xs text-muted-foreground">
          The file is uploaded when you start the run.
        </p>
      </div>

      <div className="space-y-3">
        <div className="flex items-center justify-between gap-2">
          <h4 className="text-sm font-medium">Your datasets</h4>
          <Link href="/dashboard/files">
            <Button variant="ghost" size="sm" className="gap-1.5">
              <FolderCog className="size-4" />
              Manage datasets
            </Button>
          </Link>
        </div>

        {isLoading && <Loading size="md" label="Loading datasets…" className="py-6" />}
        {error && (
          <p className="text-sm text-destructive">Failed to load your datasets.</p>
        )}
        {!isLoading && !error && compatibleFiles.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No compatible datasets yet. Upload one above to get started.
          </p>
        )}
        {!isLoading && !error && compatibleFiles.length > 0 && (
          <ul className="space-y-2">
            {compatibleFiles.map((file) => (
              <li
                key={file.id}
                className="flex items-center justify-between gap-2 rounded-lg bg-muted/50 px-3 py-2 text-sm"
              >
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{file.original_filename}</span>
                  <span className="text-muted-foreground">
                    {formatSize(file.file_size)}
                    {file.uploaded_at && ` · ${new Date(file.uploaded_at).toLocaleDateString()}`}
                  </span>
                </div>
                <Button
                  size="sm"
                  type="button"
                  onClick={() =>
                    onChoose({
                      kind: "existing",
                      fileId: file.id,
                      display: { name: file.original_filename, size: file.file_size },
                      mimeType: file.mime_type,
                    })
                  }
                >
                  Use
                </Button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="flex justify-start">
        <Button type="button" variant="outline" className="gap-1.5" onClick={onBack}>
          <ArrowLeft className="size-4" />
          Back
        </Button>
      </div>
    </div>
  );
}
