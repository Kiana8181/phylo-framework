"use client";

import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";
import FileInput from "@/components/common/FileInput";
import type { MethodSpec } from "@phylo/contracts";

export default function RunParameters({
  spec,
  files,
  onFiles,
  onSubmit,
}: {
  spec: MethodSpec;
  files: File[];
  onFiles: (files: File[]) => void;
  onSubmit: (params: Record<string, any>) => Promise<void> | void;
}) {
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
          onSubmit={onSubmit}
        />
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
