"use client";

import { Card } from "@/components/ui/card";
import type { MethodInfo } from "@phylo/contracts";
import { cn } from "@/lib/utils";

export default function MethodsGrid({
  methods,
  selectedId,
  onSelect,
  disabled = false,
}: {
  methods: MethodInfo[];
  selectedId: string | null;
  onSelect: (m: MethodInfo) => void;
  disabled?: boolean;
}) {
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      {methods.map((m) => {
        const isSelected = selectedId === m.id;
        return (
          <Card
            key={m.id}
            className={cn(
              "p-4 border transition",
              isSelected
                ? "ring-2 ring-violet-500/70 border-violet-500 dark:ring-violet-400/70 dark:border-violet-400"
                : "",
              disabled
                ? "opacity-80 cursor-not-allowed pointer-events-none hover:shadow-none"
                : "cursor-pointer hover:shadow-sm"
            )}
            onClick={() => !disabled && onSelect(m)}
            aria-disabled={disabled}
          >
            <div className="flex items-center justify-between">
              <div className="font-medium">{m.name}</div>
              <div className="flex items-center gap-1.5">
                {isSelected && disabled && (
                  <span className="text-[11px] px-2 py-0.5 rounded border border-violet-500/70 text-violet-700 dark:text-violet-300 dark:border-violet-400/80">
                    Selected
                  </span>
                )}
                <span className="text-[11px] px-2 py-0.5 rounded bg-muted text-muted-foreground">
                  v{m.version}
                </span>
              </div>
            </div>
            <p className="text-xs text-muted-foreground mt-1">ID: {m.id}</p>
          </Card>
        );
      })}
    </div>
  );
}
