"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ClipboardCopy, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import {
  resolveRunParams,
  toCopyPayload,
  type ContractSpec,
  type FormattedParamValue,
  type ResolvedParam,
} from "@/features/runs/params";

type SameDatasetRef = {
  id: string;
  methodId?: string;
  datasetName?: string | null;
};

type ParamGroup = {
  id: string;
  label: string;
  items: ResolvedParam[];
};

type RunParamsDropdownProps = {
  methodKey: string;
  runParams: Record<string, unknown> | null | undefined;
  contractSpec?: ContractSpec | null;
  runId?: string;
  datasetName?: string | null;
  datasetFiles?: string[];
  sameDatasetRuns?: SameDatasetRef[];
  dense?: boolean;
  className?: string;
};

type PanelPosition = {
  style: CSSProperties;
  bodyMaxHeight: number;
};

const DEFAULT_GROUP_ID = "__default";
const UNKNOWN_GROUP_ID = "__unknown";
const VIEWPORT_MARGIN = 12;
const PANEL_GAP = 8;

function ParamValue({ formatted, dense }: { formatted: FormattedParamValue; dense: boolean }) {
  if (formatted.kind === "chips") {
    return (
      <div className="flex flex-wrap gap-1.5">
        {formatted.chips.map((chip, idx) => (
          <span
            key={`${chip}-${idx}`}
            className={cn(
              "rounded-full border bg-muted/40 px-2 py-0.5 text-xs break-all",
              dense && "text-[11px]"
            )}
          >
            {chip}
          </span>
        ))}
      </div>
    );
  }

  if (formatted.kind === "json") {
    return (
      <details className="rounded border bg-card/40 p-2">
        <summary className="cursor-pointer text-[11px] font-medium">Show JSON value</summary>
        <pre className="mt-2 whitespace-pre-wrap break-words text-[11px]">{formatted.json}</pre>
      </details>
    );
  }

  return <p className={cn("text-xs break-words", dense && "text-[11px]")}>{formatted.text}</p>;
}

function buildGroups(
  spec: ContractSpec | undefined | null,
  knownItems: ResolvedParam[]
): ParamGroup[] {
  const byId = new Map<string, ParamGroup>();
  const order: string[] = [];

  (spec?.sections ?? []).forEach((section) => {
    byId.set(section.id, { id: section.id, label: section.label, items: [] });
    order.push(section.id);
  });

  knownItems.forEach((item) => {
    const groupId = item.section || DEFAULT_GROUP_ID;
    if (!byId.has(groupId)) {
      byId.set(groupId, {
        id: groupId,
        label: item.section || "Parameters",
        items: [],
      });
      order.push(groupId);
    }
    byId.get(groupId)?.items.push(item);
  });

  return order
    .map((groupId) => byId.get(groupId))
    .filter((group): group is ParamGroup => Boolean(group && group.items.length > 0));
}

function MetaRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-0.5">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="text-xs break-words">{value}</p>
    </div>
  );
}

function RunParamsDropdownImpl({
  methodKey,
  runParams,
  contractSpec,
  runId,
  datasetName,
  datasetFiles,
  sameDatasetRuns,
  dense = false,
  className,
}: RunParamsDropdownProps) {
  const [open, setOpen] = useState(false);
  const [mounted, setMounted] = useState(false);
  const [panelPosition, setPanelPosition] = useState<PanelPosition | null>(null);

  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const resolved = useMemo(
    () => resolveRunParams(contractSpec ?? undefined, runParams),
    [contractSpec, runParams]
  );

  const groups = useMemo(() => buildGroups(contractSpec, resolved.known), [contractSpec, resolved.known]);
  const datasetLabel = useMemo(() => {
    if (datasetName && datasetName.trim()) return datasetName;
    if (datasetFiles && datasetFiles.length) return datasetFiles.join(", ");
    return "Dataset unavailable";
  }, [datasetFiles, datasetName]);

  const sameDatasetLabel = useMemo(() => {
    if (!sameDatasetRuns) return "—";
    if (!sameDatasetRuns.length) return "None";
    return `${sameDatasetRuns.length} run${sameDatasetRuns.length !== 1 ? "s" : ""}`;
  }, [sameDatasetRuns]);

  const updatePanelPosition = useCallback(() => {
    if (!triggerRef.current || typeof window === "undefined") return;

    const triggerRect = triggerRef.current.getBoundingClientRect();
    const desiredWidth = dense ? 544 : 832;
    const width = Math.min(desiredWidth, window.innerWidth - VIEWPORT_MARGIN * 2);

    const preferredLeft = dense ? triggerRect.right - width : triggerRect.left;
    const left = Math.max(
      VIEWPORT_MARGIN,
      Math.min(preferredLeft, window.innerWidth - width - VIEWPORT_MARGIN)
    );

    const maxPanelHeight = Math.min(Math.floor(window.innerHeight * 0.74), 544);
    const topSpace = triggerRect.top - PANEL_GAP - VIEWPORT_MARGIN;
    const bottomSpace = window.innerHeight - triggerRect.bottom - PANEL_GAP - VIEWPORT_MARGIN;

    const renderAbove = bottomSpace < 240 && topSpace > bottomSpace;
    const bodyMaxHeight = Math.max(
      180,
      Math.min(maxPanelHeight, renderAbove ? topSpace : bottomSpace > 0 ? bottomSpace : maxPanelHeight)
    );

    const top = renderAbove
      ? Math.max(VIEWPORT_MARGIN, triggerRect.top - PANEL_GAP - bodyMaxHeight - 96)
      : Math.min(
          triggerRect.bottom + PANEL_GAP,
          window.innerHeight - VIEWPORT_MARGIN - bodyMaxHeight - 96
        );

    setPanelPosition({
      style: {
        position: "fixed",
        top,
        left,
        width,
        zIndex: 90,
      },
      bodyMaxHeight,
    });
  }, [dense]);

  useEffect(() => {
    setMounted(true);
  }, []);

  useEffect(() => {
    if (!open) return;

    updatePanelPosition();

    const onDocumentMouseDown = (event: MouseEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (rootRef.current?.contains(target)) return;
      if (panelRef.current?.contains(target)) return;
      setOpen(false);
    };

    const onEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };

    const onViewportChange = () => updatePanelPosition();

    document.addEventListener("mousedown", onDocumentMouseDown);
    document.addEventListener("keydown", onEscape);
    window.addEventListener("resize", onViewportChange);
    window.addEventListener("scroll", onViewportChange, true);

    return () => {
      document.removeEventListener("mousedown", onDocumentMouseDown);
      document.removeEventListener("keydown", onEscape);
      window.removeEventListener("resize", onViewportChange);
      window.removeEventListener("scroll", onViewportChange, true);
    };
  }, [open, updatePanelPosition]);

  const handleCopy = async () => {
    try {
      const text = toCopyPayload({ methodKey, runId, resolved });
      await navigator.clipboard.writeText(text);
      notify.success("Parameters copied");
    } catch {
      notify.error("Could not copy parameters");
    }
  };

  const panel = open && panelPosition && (
    <div ref={panelRef} className="rounded-xl border bg-popover shadow-xl" style={panelPosition.style}>
      <div
        className="space-y-3 overflow-y-auto overscroll-contain p-3"
        style={{ maxHeight: panelPosition.bodyMaxHeight }}
      >
        <div className="rounded-lg border bg-card/50 p-3">
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
            <MetaRow label="Run ID" value={runId ?? "—"} />
            <MetaRow label="Method" value={contractSpec?.methodLabel || methodKey} />
            <MetaRow label="Dataset" value={datasetLabel} />
            <MetaRow label="Same Datasets" value={sameDatasetLabel} />
          </div>
        </div>

        {resolved.setCount === 0 ? (
          <p className="rounded-lg border bg-card/40 p-3 text-sm text-muted-foreground">
            No parameters were set for this run.
          </p>
        ) : (
          <details className="rounded border p-3 bg-card/50 overflow-x-auto" open={!dense}>
            <summary className="cursor-pointer text-sm font-medium">Show parameter list</summary>
            <div className="mt-2 space-y-3">
              {groups.map((group) => (
                <div key={group.id} className="space-y-2">
                  {group.id !== DEFAULT_GROUP_ID && (
                    <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                      {group.label}
                    </p>
                  )}
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {group.items.map((item) => (
                      <div key={item.key} className="rounded-lg border bg-background/70 p-2">
                        <p className="text-xs font-medium">{item.label}</p>
                        {item.description && (
                          <p className="mt-0.5 text-[11px] text-muted-foreground">{item.description}</p>
                        )}
                        <div className="mt-1.5">
                          <ParamValue formatted={item.formatted} dense={dense} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}

              {resolved.unknown.length > 0 && (
                <div className="space-y-2">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                    Other / Unknown
                  </p>
                  <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                    {resolved.unknown.map((item) => (
                      <div key={`${UNKNOWN_GROUP_ID}-${item.key}`} className="rounded-lg border bg-background/70 p-2">
                        <p className="text-xs font-medium">{item.key}</p>
                        <div className="mt-1.5">
                          <ParamValue formatted={item.formatted} dense={dense} />
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </details>
        )}
      </div>

      <div className="flex items-center justify-end border-t px-3 py-2">
        <Button type="button" variant="outline" size="sm" onClick={handleCopy} className="gap-1.5">
          <ClipboardCopy className="h-3.5 w-3.5" />
          Copy params JSON
        </Button>
      </div>
    </div>
  );

  return (
    <div ref={rootRef} className={cn("inline-flex", className)}>
      <Button
        ref={triggerRef}
        type="button"
        variant="outline"
        size={dense ? "sm" : "default"}
        onClick={() => setOpen((prev) => !prev)}
        className={cn("gap-1.5", dense && "h-8 px-2 text-xs")}
      >
        <SlidersHorizontal className={cn("h-4 w-4", dense && "h-3.5 w-3.5")} />
        Parameters ({resolved.setCount})
        <ChevronDown className={cn("h-4 w-4 transition-transform", open && "rotate-180", dense && "h-3.5 w-3.5")} />
      </Button>

      {mounted && panel ? createPortal(panel, document.body) : null}
    </div>
  );
}

const RunParamsDropdown = memo(RunParamsDropdownImpl);

export default RunParamsDropdown;
