"use client";

import { memo, useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { ChevronDown, ClipboardCopy, SlidersHorizontal } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { notify } from "@/lib/notify";
import { resolveRunParams, toCopyPayload, type ContractSpec } from "@/features/runs/params";
import RunParamsContent from "@/components/runs/RunParamsContent";

type SameDatasetRef = {
  id: string;
  methodId?: string;
  datasetName?: string | null;
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

const VIEWPORT_MARGIN = 12;
const PANEL_GAP = 8;

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
    [contractSpec, runParams],
  );

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
      Math.min(preferredLeft, window.innerWidth - width - VIEWPORT_MARGIN),
    );

    const maxPanelHeight = Math.min(Math.floor(window.innerHeight * 0.74), 544);
    const topSpace = triggerRect.top - PANEL_GAP - VIEWPORT_MARGIN;
    const bottomSpace = window.innerHeight - triggerRect.bottom - PANEL_GAP - VIEWPORT_MARGIN;

    const renderAbove = bottomSpace < 240 && topSpace > bottomSpace;
    const bodyMaxHeight = Math.max(
      180,
      Math.min(maxPanelHeight, renderAbove ? topSpace : bottomSpace > 0 ? bottomSpace : maxPanelHeight),
    );

    const top = renderAbove
      ? Math.max(VIEWPORT_MARGIN, triggerRect.top - PANEL_GAP - bodyMaxHeight - 96)
      : Math.min(
          triggerRect.bottom + PANEL_GAP,
          window.innerHeight - VIEWPORT_MARGIN - bodyMaxHeight - 96,
        );

    setPanelPosition({
      style: { position: "fixed", top, left, width, zIndex: 90 },
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
      await navigator.clipboard.writeText(toCopyPayload({ methodKey, runId, resolved }));
      notify.success("Parameters copied");
    } catch {
      notify.error("Could not copy parameters");
    }
  };

  const panel = open && panelPosition && (
    <div ref={panelRef} className="rounded-xl border bg-popover shadow-xl" style={panelPosition.style}>
      <div className="overflow-y-auto overscroll-contain p-3" style={{ maxHeight: panelPosition.bodyMaxHeight }}>
        <RunParamsContent
          methodKey={methodKey}
          contractSpec={contractSpec}
          runId={runId}
          resolved={resolved}
          datasetLabel={datasetLabel}
          sameDatasetLabel={sameDatasetLabel}
          dense={dense}
        />
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
