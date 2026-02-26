"use client";

import { Info } from "lucide-react";
import { cn } from "@/lib/utils";

export const SEQUENCE_TRACE_TOOLTIP_TEXT =
  "Track the position of selected sequences across phylogenetic trees built with different algorithms.";

type SequenceTraceInfoIconProps = {
  className?: string;
};

export default function SequenceTraceInfoIcon({ className }: SequenceTraceInfoIconProps) {
  return (
    <button
      type="button"
      aria-label="What is Sequence Trace?"
      title={SEQUENCE_TRACE_TOOLTIP_TEXT}
      className={cn(
        "inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-sm text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className,
      )}
    >
      <Info className="h-3.5 w-3.5" aria-hidden="true" />
    </button>
  );
}
