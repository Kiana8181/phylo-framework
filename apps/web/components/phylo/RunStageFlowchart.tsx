"use client";

import { useMemo } from "react";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";
import { computeNodes, type RenderNode } from "./runStageNodes";

const DOT_BY_STATE: Record<RenderNode["state"], string> = {
  done: "border-primary bg-primary text-primary-foreground",
  active: "border-primary/50 bg-primary/10 text-primary",
  pending: "border-border bg-muted text-muted-foreground",
  error: "border-destructive bg-destructive/10 text-destructive",
  cancelled: "border-dashed border-destructive/60 bg-destructive/5 text-destructive",
};

const LABEL_BY_STATE: Record<RenderNode["state"], string> = {
  done: "text-foreground",
  active: "font-medium text-foreground",
  pending: "text-muted-foreground",
  error: "font-medium text-destructive",
  cancelled: "text-destructive",
};

/** Animated dashed ring around the currently-running stage. */
function MarchingRing() {
  return (
    <svg
      className="pointer-events-none absolute inset-[-4px] h-[calc(100%+8px)] w-[calc(100%+8px)] text-primary"
      viewBox="0 0 36 36"
      fill="none"
      aria-hidden="true"
    >
      <circle
        cx="18"
        cy="18"
        r="16"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeDasharray="5 4"
        className="phylo-marching"
      />
    </svg>
  );
}

export default function RunStageFlowchart({
  methodId,
  status,
  stage,
}: {
  methodId?: string | null;
  status?: string;
  stage?: string | null;
  progress?: number;
  stageMessage?: string | null;
}) {
  const nodes = useMemo(() => computeNodes(methodId, status, stage), [methodId, status, stage]);

  return (
    <div className="space-y-2">
      <span className="text-xs font-medium text-muted-foreground">Pipeline</span>
      <div className="flex justify-center">
        <ol className="flex flex-wrap items-start justify-center gap-y-3">
        {nodes.map((node, i) => {
          const isLast = i === nodes.length - 1;
          return (
            <li key={`${node.id}-${i}`} className="flex items-start">
              <div className="flex w-[84px] flex-col items-center gap-1 text-center">
                <span className="relative flex size-7 items-center justify-center">
                  {node.state === "active" && <MarchingRing />}
                  <span
                    className={cn(
                      "flex size-7 items-center justify-center rounded-full border text-[11px] font-semibold",
                      DOT_BY_STATE[node.state],
                    )}
                  >
                    {node.state === "done" ? (
                      <Check className="size-4" />
                    ) : node.state === "error" || node.state === "cancelled" ? (
                      <X className="size-4" />
                    ) : (
                      i + 1
                    )}
                  </span>
                </span>
                <span className={cn("text-[11px] leading-tight", LABEL_BY_STATE[node.state])}>
                  {node.label}
                </span>
              </div>
              {!isLast && (
                <span
                  className={cn(
                    "mt-[13px] h-px w-5 sm:w-7",
                    node.state === "done" ? "bg-primary" : "bg-border",
                  )}
                  aria-hidden="true"
                />
              )}
            </li>
          );
        })}
        </ol>
      </div>
    </div>
  );
}
