"use client";

import { useMemo, useState } from "react";
import { ChevronDown, ClipboardCopy, SlidersHorizontal, Wand2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import { resolveRunParams, toCopyPayload, type ContractSpec } from "@/features/runs/params";
import RunParamsContent from "@/components/runs/RunParamsContent";

export default function RunParamsPanel({
  methodKey,
  runParams,
  contractSpec,
  runId,
  datasetName,
  datasetFiles,
  onUseAsDefaults,
  className,
}: {
  methodKey: string;
  runParams: Record<string, unknown> | null | undefined;
  contractSpec?: ContractSpec | null;
  runId?: string;
  datasetName?: string | null;
  datasetFiles?: string[];
  onUseAsDefaults?: () => void;
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  const resolved = useMemo(
    () => resolveRunParams(contractSpec ?? undefined, runParams),
    [contractSpec, runParams],
  );

  const datasetLabel = useMemo(() => {
    if (datasetName && datasetName.trim()) return datasetName;
    if (datasetFiles && datasetFiles.length) return datasetFiles.join(", ");
    return "Dataset unavailable";
  }, [datasetFiles, datasetName]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(toCopyPayload({ methodKey, runId, resolved }));
      notify.success("Parameters copied");
    } catch {
      notify.error("Could not copy parameters");
    }
  };

  return (
    <div className={cn("w-full rounded-lg border bg-card/30", className)}>
      <button
        type="button"
        onClick={() => setOpen((prev) => !prev)}
        aria-expanded={open}
        className="flex w-full items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-medium">
          <SlidersHorizontal className="size-4 text-muted-foreground" />
          Parameters ({resolved.setCount})
        </span>
        <ChevronDown className={cn("size-4 transition-transform", open && "rotate-180")} />
      </button>

      {open && (
        <div className="space-y-3 border-t p-4">
          <RunParamsContent
            methodKey={methodKey}
            contractSpec={contractSpec}
            runId={runId}
            resolved={resolved}
            datasetLabel={datasetLabel}
            listOpen
          />

          <div className="flex flex-wrap items-center justify-end gap-2 border-t pt-3">
            <Button type="button" variant="outline" size="sm" onClick={handleCopy} className="gap-1.5">
              <ClipboardCopy className="size-3.5" />
              Copy params JSON
            </Button>
            {onUseAsDefaults && (
              <Button type="button" size="sm" onClick={onUseAsDefaults} className="gap-1.5">
                <Wand2 className="size-3.5" />
                Use as defaults for next run
              </Button>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
