"use client";

import { useEffect, useMemo, useState } from "react";
import { ArrowLeft } from "lucide-react";
import { Button } from "@/components/ui/button";
import FormBuilder from "@/components/ui/FormBuilder";
import { inputFormatFromFile } from "@/lib/fileTypes";
import { classifyFastaFile, type FastaIdStyle } from "@/lib/fastaIdStyle";
import { useFastaIdStyle } from "@/features/files/hooks";
import type { MethodSpec } from "@phylo/contracts";
import { chosenInputMime, chosenInputName, type ChosenInput } from "./types";

export default function ParametersStep({
  spec,
  chosen,
  defaults,
  onRun,
  onBack,
  runBlockedReason,
}: {
  spec: MethodSpec;
  chosen: ChosenInput;
  defaults?: Record<string, unknown>;
  onRun: (values: Record<string, unknown>) => void | Promise<void>;
  onBack: () => void;
  /** Set while a run limit is reached: the Run button is disabled and says why. */
  runBlockedReason?: string | null;
}) {
  const schema = useMemo(
    () => ({ ...(spec.paramSchema ?? {}), uiHints: spec.uiHints }),
    [spec.paramSchema, spec.uiHints],
  );

  const inputFormat = useMemo(
    () => inputFormatFromFile({ name: chosenInputName(chosen), mimeType: chosenInputMime(chosen) }),
    [chosen],
  );

  const isFasta = inputFormat === "fasta";
  const [uploadIdStyle, setUploadIdStyle] = useState<FastaIdStyle>();
  useEffect(() => {
    if (!isFasta || chosen.kind !== "upload") {
      setUploadIdStyle(undefined);
      return;
    }
    let cancelled = false;
    classifyFastaFile(chosen.file).then((style) => {
      if (!cancelled) setUploadIdStyle(style);
    });
    return () => {
      cancelled = true;
    };
  }, [isFasta, chosen]);

  const existingIdStyle = useFastaIdStyle(chosen.kind === "existing" ? chosen.fileId : undefined, {
    enabled: isFasta,
  });

  const fastaIdStyle = chosen.kind === "upload" ? uploadIdStyle : existingIdStyle.data?.style;

  const context = useMemo(
    () => ({ $inputFormat: inputFormat, $fastaIdStyle: fastaIdStyle }),
    [inputFormat, fastaIdStyle],
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-card/40 px-4 py-3">
        <div className="min-w-0">
          <p className="text-sm font-medium">{spec.name}</p>
          <p className="truncate text-xs text-muted-foreground">Input: {chosenInputName(chosen)}</p>
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
        context={context}
        submitDisabled={!!runBlockedReason}
        submitDisabledReason={runBlockedReason ?? undefined}
      />
    </div>
  );
}
