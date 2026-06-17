"use client";

import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { MethodInfo } from "@phylo/contracts";
import { cn } from "@/lib/utils";
import type { ComponentType, SVGProps } from "react";
import {
  Check,
  ExternalLink,
  GitBranch,
  Network,
  Sparkles,
  TreePine,
  Workflow,
} from "lucide-react";

type IconComponent = ComponentType<SVGProps<SVGSVGElement> & { size?: number | string }>;

const METHOD_ICONS: Record<string, IconComponent> = {
  brepphylo: GitBranch,
  clonaltree: Network,
  dowser: Sparkles,
  gctree: TreePine,
};

function getMethodIcon(id: string): IconComponent {
  return METHOD_ICONS[id] ?? Workflow;
}

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
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {methods.map((m) => {
        const isSelected = selectedId === m.id;
        const Icon = getMethodIcon(m.id);
        return (
          <Card
            key={m.id}
            className={cn(
              "p-5 border transition gap-3",
              isSelected
                ? "ring-2 ring-violet-500/70 border-violet-500 dark:ring-violet-400/70 dark:border-violet-400"
                : "",
              disabled
                ? "opacity-80 cursor-not-allowed pointer-events-none hover:shadow-none"
                : "cursor-pointer hover:shadow-md hover:border-violet-300/50 dark:hover:border-violet-500/30"
            )}
            onClick={() => !disabled && onSelect(m)}
            aria-disabled={disabled}
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex items-start gap-3 min-w-0">
                <div
                  className={cn(
                    "flex items-center justify-center rounded-lg size-9 shrink-0",
                    "bg-violet-100 text-violet-700 dark:bg-violet-500/15 dark:text-violet-300"
                  )}
                >
                  <Icon className="size-5" />
                </div>
                <div className="min-w-0">
                  <div className="font-semibold leading-tight truncate">{m.name}</div>
                  {m.tagline && (
                    <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                      {m.tagline}
                    </p>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1.5 shrink-0">
                {m.category && (
                  <Badge variant="secondary" className="text-[10px]">
                    {m.category}
                  </Badge>
                )}
                {isSelected && disabled && (
                  <Badge
                    variant="outline"
                    className="text-[10px] border-violet-500/70 text-violet-700 dark:text-violet-300 dark:border-violet-400/80"
                  >
                    Selected
                  </Badge>
                )}
              </div>
            </div>

            {m.summary && (
              <p className="text-sm text-muted-foreground leading-relaxed">{m.summary}</p>
            )}

            {m.inputFormats && m.inputFormats.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 font-medium mb-1.5">
                  Accepts
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {m.inputFormats.map((fmt) => (
                    <Badge key={fmt} variant="muted" className="text-[10px]">
                      {fmt}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {m.capabilities && m.capabilities.length > 0 && (
              <div>
                <div className="text-[10px] uppercase tracking-wider text-muted-foreground/80 font-medium mb-1.5">
                  Capabilities
                </div>
                <ul className="space-y-1">
                  {m.capabilities.map((cap) => (
                    <li key={cap} className="flex items-start gap-2 text-xs text-foreground/80">
                      <Check className="size-3.5 text-violet-600 dark:text-violet-400 shrink-0 mt-0.5" />
                      <span>{cap}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex items-center justify-between pt-1 mt-auto">
              {m.externalDocUrl ? (
                <a
                  href={m.externalDocUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  onClick={(e) => e.stopPropagation()}
                  className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  <ExternalLink className="size-3" />
                  {m.externalDocLabel ?? "Docs"}
                </a>
              ) : (
                <span />
              )}
              <Button
                type="button"
                size="sm"
                variant={isSelected ? "secondary" : "default"}
                disabled={disabled}
                onClick={(e) => {
                  e.stopPropagation();
                  if (!disabled) onSelect(m);
                }}
              >
                {isSelected ? "Selected" : "Select"}
              </Button>
            </div>
          </Card>
        );
      })}
    </div>
  );
}
