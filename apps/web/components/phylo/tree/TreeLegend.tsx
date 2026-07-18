"use client";

import { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import type { ColorScale } from "@/components/phylo/tree/core";

/**
 * Compact, collapsible colour legend overlaid top-left of the tree pane. A colour
 * scale without a key is decoration, not encoding — so this is required whenever a
 * field is being coloured. Clicking a categorical entry rings the matching nodes.
 */
export default function TreeLegend({
  scale,
  activeColor,
  onToggle,
}: {
  scale: ColorScale;
  activeColor: string | null;
  onToggle: (color: string) => void;
}) {
  const [open, setOpen] = useState(true);

  if (scale.kind === "none" || !scale.field) return null;

  const title = scale.field;

  return (
    <div className="absolute left-3 top-3 max-w-[220px] rounded-md border bg-background/90 text-xs shadow-sm backdrop-blur">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center gap-1 px-2 py-1.5 font-medium"
        aria-expanded={open}
      >
        {open ? <ChevronDown className="size-3.5" /> : <ChevronRight className="size-3.5" />}
        <span className="truncate">Colour: {title}</span>
      </button>

      {open && (
        <div className="max-h-[240px] overflow-auto px-2 pb-2">
          {scale.legend.kind === "continuous" && (
            <div className="space-y-1">
              <div
                className="h-3 w-full rounded"
                style={{
                  background: `linear-gradient(to right, ${scale.legend.ramp.join(", ")})`,
                }}
              />
              <div className="flex justify-between text-[10px] text-muted-foreground">
                <span>{formatNum(scale.legend.min)}</span>
                <span>{formatNum(scale.legend.max)}</span>
              </div>
            </div>
          )}

          {scale.legend.kind === "categorical" && (
            <ul className="space-y-0.5">
              {scale.legend.entries.map((entry) => {
                const active = activeColor === entry.color;
                return (
                  <li key={entry.key}>
                    <button
                      type="button"
                      onClick={() => onToggle(entry.color)}
                      className={`flex w-full items-center gap-1.5 rounded px-1 py-0.5 text-left hover:bg-accent ${
                        active ? "ring-1 ring-[var(--tree-match)]" : ""
                      }`}
                      title={`${entry.label} (${entry.count})`}
                    >
                      <span
                        className="size-3 shrink-0 rounded-sm border"
                        style={{ background: entry.color }}
                      />
                      <span className="min-w-0 flex-1 truncate">{entry.label}</span>
                      <span className="shrink-0 tabular-nums text-muted-foreground">{entry.count}</span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}

          {scale.hasUnknown && (
            <div className="mt-1 flex items-center gap-1.5 px-1 text-muted-foreground">
              <span
                className="size-3 shrink-0 rounded-sm border"
                style={{ background: scale.unknownColor }}
              />
              <span>no value</span>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function formatNum(n: number): string {
  if (!Number.isFinite(n)) return "—";
  if (Number.isInteger(n)) return String(n);
  return n.toFixed(2);
}
