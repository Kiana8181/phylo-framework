"use client";

import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";
import FileInput from "@/components/common/FileInput";
import type { MethodSpec } from "@phylo/contracts";
import { useState } from "react";
import { useCreateRun } from "@/features/runs/hooks";
import { Button } from "@/components/ui/button";
import { Progress } from "../ui/progress";

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

  const requiresFile = !!spec?.uiHints?.requiresFile;
  const maxFiles = spec?.uiHints?.maxFiles ?? 1;

  async function handleSubmit(params: Record<string, any>) {
    const { notify } = await import("@/lib/notify");

    // basic validations
    if (requiresFile && (!files || files.length === 0)) {
      notify.error("File required", "Please attach a file for this method.");
      return;
    }
    if (maxFiles === 1 && files && files.length > 1) {
      notify.error("Only one file allowed", "Please attach exactly one file.");
      return;
    }

    const fd = new FormData();
    fd.set("params", JSON.stringify(params));

    if (files && files.length) {
      if (maxFiles === 1) {
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
        <FormBuilder
          schema={{ ...spec.paramSchema, uiHints: spec.uiHints }}
          onSubmit={handleSubmit}
        />

        {uploadPct !== null && (
          <div className="space-y-1">
            <div className="text-xs text-muted-foreground">
              Uploading… {uploadPct}%
            </div>
            <Progress value={uploadPct} />
          </div>
        )}

        {createRun.isPending && uploadPct === null && (
          <div className="text-xs text-muted-foreground">Starting run…</div>
        )}
      </Card>

      <Card className="p-4 space-y-3">
        <div>
          <h3 className="text-lg font-medium">Upload data</h3>
          <p className="text-xs text-muted-foreground">
            Accepted: {spec.accepts.join(", ")}
          </p>
        </div>
        <FileInput multiple accept={spec.accepts.join(",")} onFiles={onFiles} />
        {files?.length ? (
          <ul className="text-xs text-muted-foreground mt-2 space-y-1">
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
