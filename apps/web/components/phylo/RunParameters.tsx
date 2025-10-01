"use client";

import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";
import FileInput from "@/components/common/FileInput";
import type { MethodSpec } from "@phylo/contracts";
import { useMemo, useState } from "react";
import { useCreateRun } from "@/features/runs/hooks";
import { Button } from "@/components/ui/button";
import { notify } from "@/lib/notify";

export default function RunParameters({
  spec,
  files,
  onFiles,
  onSubmitDone,
}: {
  spec: MethodSpec;
  files: File[];
  onFiles: (files: File[]) => void;
  onSubmitDone?: (runId: string) => void;
}) {
  const createRun = useCreateRun();
  const [uploadPct, setUploadPct] = useState<number | null>(null);

  const schemaMemo = useMemo(
    () => ({ ...(spec.paramSchema ?? {}), uiHints: spec.uiHints }),
    [spec.id, spec.paramSchema, spec.uiHints]
  );

  async function handleSubmit(values: Record<string, any>) {
    const fd = new FormData();
    fd.set("params", JSON.stringify(values ?? {}));

    const maxFiles = Number(spec.uiHints?.maxFiles ?? 1);
    if (files?.length) {
      if (maxFiles <= 1) {
        const f = files[0];
        fd.set("file", f, f.name);
      } else {
        files.forEach((f) => fd.append("file", f, f.name));
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
    <section className="grid gap-4 md:grid-cols-2">
      <Card className="p-4 space-y-4">
        <div>
          <h3 className="text-lg font-medium">{spec.name} parameters</h3>
          <p className="text-xs text-muted-foreground">
            Configure inputs for this method
          </p>
        </div>
        <FormBuilder schema={schemaMemo} onSubmit={handleSubmit} />

        {uploadPct !== null && (
          <div className="space-y-2">
            <div className="text-sm">
              Uploading{Number.isFinite(uploadPct) ? ` (${uploadPct}%)` : ""}
            </div>
            <div className="h-2 w-full bg-muted rounded overflow-hidden">
              <div
                className="h-full rounded bg-gradient-to-r from-blue-500 to-indigo-500 transition-[width]"
                style={{ width: `${uploadPct ?? 0}%` }}
              />
            </div>
          </div>
        )}
      </Card>

      <Card className="p-4 space-y-4">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-lg font-medium">Input files</h3>
            <p className="text-xs text-muted-foreground">
              Accepted: {(spec?.accepts ?? []).join(", ") || "—"}
            </p>
          </div>
          <Button
            variant="outline"
            onClick={() => onFiles([])}
            disabled={!files?.length}
          >
            Clear
          </Button>
        </div>

        <FileInput
          accept={(spec?.accepts ?? []).join(",")}
          multiple={(spec?.uiHints?.maxFiles ?? 1) > 1}
          onFiles={onFiles}
        />

        {files?.length ? (
          <ul className="space-y-1 text-sm">
            {files.map((f, i) => (
              <li key={i} className="truncate">
                • {f.name}
              </li>
            ))}
          </ul>
        ) : (
          <div className="text-xs text-muted-foreground">
            No files selected.
          </div>
        )}
      </Card>
    </section>
  );
}
