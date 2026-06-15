"use client";

import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export type WizardStepIndex = 1 | 2 | 3 | 4;

const STEPS: { index: WizardStepIndex; label: string }[] = [
  { index: 1, label: "Method" },
  { index: 2, label: "Data" },
  { index: 3, label: "Parameters" },
  { index: 4, label: "Run" },
];

export default function WizardStepper({
  current,
  onStepClick,
}: {
  current: WizardStepIndex;
  /** Invoked when the user clicks an already-completed step to go back. */
  onStepClick?: (step: WizardStepIndex) => void;
}) {
  return (
    <ol className="flex items-center gap-2 sm:gap-3">
      {STEPS.map((step, i) => {
        const done = step.index < current;
        const active = step.index === current;
        const clickable = done && !!onStepClick;
        return (
          <li key={step.index} className="flex flex-1 items-center gap-2 sm:gap-3">
            <button
              type="button"
              disabled={!clickable}
              onClick={() => clickable && onStepClick?.(step.index)}
              className={cn(
                "flex items-center gap-2 rounded-full px-1.5 py-1 transition",
                clickable ? "cursor-pointer hover:opacity-80" : "cursor-default",
              )}
              aria-current={active ? "step" : undefined}
            >
              <span
                className={cn(
                  "flex size-7 shrink-0 items-center justify-center rounded-full border text-xs font-semibold transition",
                  done && "border-primary bg-primary text-primary-foreground",
                  active && "border-primary text-primary ring-2 ring-primary/30",
                  !done && !active && "border-border text-muted-foreground",
                )}
              >
                {done ? <Check className="size-4" /> : step.index}
              </span>
              <span
                className={cn(
                  "text-sm font-medium",
                  active ? "text-foreground" : "text-muted-foreground",
                )}
              >
                {step.label}
              </span>
            </button>
            {i < STEPS.length - 1 && (
              <span
                className={cn(
                  "h-px flex-1 transition",
                  step.index < current ? "bg-primary" : "bg-border",
                )}
              />
            )}
          </li>
        );
      })}
    </ol>
  );
}
