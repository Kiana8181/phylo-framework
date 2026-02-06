"use client";

import { Card } from "@/components/ui/card";
import type { MethodInfo } from "@phylo/contracts";

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
      {methods.map((m) => (
        <Card
          key={m.id}
          className={`p-4 border transition hover:shadow-sm ${
            selectedId === m.id ? "ring-2 ring-primary border-primary/30" : ""
          } ${disabled ? "opacity-60 pointer-events-none" : "cursor-pointer"}`}
          onClick={() => !disabled && onSelect(m)}
        >
          <div className="flex items-center justify-between">
            <div className="font-medium">{m.name}</div>
            <span className="text-[11px] px-2 py-0.5 rounded bg-muted text-muted-foreground">
              v{m.version}
            </span>
          </div>
          <p className="text-xs text-muted-foreground mt-1">ID: {m.id}</p>
        </Card>
      ))}
    </div>
  );
}
