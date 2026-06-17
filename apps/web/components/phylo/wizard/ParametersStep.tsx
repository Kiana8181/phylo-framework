"use client";

import { useMemo } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import FormBuilder from "@/components/ui/FormBuilder";
import { inputFormatFromFile } from "@/lib/fileTypes";
import type { MethodSpec } from "@phylo/contracts";
import { chosenInputMime, chosenInputName, type ChosenInput } from "./types";

export default function ParametersStep({
  spec,
  chosen,
  defaults,
  onRun,
  onBack,
}: {
  spec: MethodSpec;
  chosen: ChosenInput;
  defaults?: Record<string, unknown>;
  onRun: (values: Record<string, unknown>) => void | Promise<void>;
  onBack: () => void;
}) {
  const schema = useMemo(
    () => ({ ...(spec.paramSchema ?? {}), uiHints: spec.uiHints }),
    [spec.paramSchema, spec.uiHints],
  );

  const inputFormat = useMemo(
    () => inputFormatFromFile({ name: chosenInputName(chosen), mimeType: chosenInputMime(chosen) }),
    [chosen],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card/40 px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{spec.name}</p>
          <p className="truncate text-xs text-muted-foreground">
            Input: {chosenInputName(chosen)}
          </p>
        </div>
        <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={onBack}>
          <ArrowLeft className="size-4" />
          Change data
        </Button>
      </div>

      <FormBuilder
        schema={schema}
        defaults={defaults}
        onSubmit={onRun}
        context={{ $inputFormat: inputFormat }}
      />
    </div>
  );
}
