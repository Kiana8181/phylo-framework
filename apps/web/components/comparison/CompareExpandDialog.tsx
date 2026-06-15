"use client";

import { memo, useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import { Spinner } from "@/components/ui/loading";
import type { LineagePlot, RunTreeListItem, TreeNodeAttrs } from "@phylo/contracts";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunsApi } from "@/features/runs/api";
import LineageSVG from "@/components/LineageSVG";
import TreeSVG from "@/components/TreeSVG";
import TreeZoomPane from "@/components/comparison/TreeZoomPane";
import SequenceTraceInfoIcon from "@/components/sequence-trace/SequenceTraceInfoIcon";

export type CompareExpandTreeRef = {
  panelId: string;
  title: string;
  runId: string;
  treeIndex: number;
};

type CompareExpandDialogProps = {
  open: boolean;
  onOpenChange: (nextOpen: boolean) => void;
  trees: CompareExpandTreeRef[];
  highlightText: string;
  displayIdField: string;
  showLabels: boolean;
};

type ExpandTreeTileProps = {
  open: boolean;
  treeRef: CompareExpandTreeRef;
  highlightText: string;
  displayIdField: string;
  showLabels: boolean;
};

function useRunStatus(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runStatus", runId],
    queryFn: () => RunsApi.status(runId!),
    enabled: !!runId && enabled,
    refetchInterval: false,
  });
}

function useRunTrees(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runTrees", runId],
    queryFn: () => RunsApi.trees(runId!),
    enabled: !!runId && enabled,
  });
}

function useTreePayload(runId: string | null, treeId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runTree", runId, treeId],
    queryFn: () => RunsApi.tree(runId!, treeId!),
    enabled: !!runId && !!treeId && enabled,
  });
}

function treeStatusLabel(tree: RunTreeListItem | undefined, treeIndex: number): string {
  const cloneText = String(tree?.cloneId ?? "").trim();
  if (cloneText) return `Tree ${treeIndex + 1} (clone ${cloneText})`;
  return `Tree ${treeIndex + 1}`;
}

const ExpandTreeTile = memo(function ExpandTreeTile({
  open,
  treeRef,
  highlightText,
  displayIdField,
  showLabels,
}: ExpandTreeTileProps) {
  const { data: status, isLoading: statusLoading } = useRunStatus(treeRef.runId, open);
  const done = status?.status === "DONE";
  const { data: treesResponse, isLoading: treesLoading } = useRunTrees(treeRef.runId, open && done);
  const trees = treesResponse?.trees ?? [];

  const resolvedTreeIndex =
    trees.length === 0 ? 0 : Math.max(0, Math.min(treeRef.treeIndex, trees.length - 1));
  const tree = trees[resolvedTreeIndex] as RunTreeListItem | undefined;
  const treeId = tree?.treeId ?? null;

  const { data: payload, isLoading: payloadLoading } = useTreePayload(
    treeRef.runId,
    treeId,
    open && done && !!treeId,
  );

  const lineagePlot = payload?.lineage_plot as LineagePlot | null | undefined;
  const nodeAttributes = (payload?.node_attributes ?? undefined) as
    | Record<string, TreeNodeAttrs>
    | undefined;
  const newickText = payload?.original_newick ?? payload?.newick ?? "";
  const hasLineage = tree?.hasLineagePlot ?? false;
  const hasNewick = Boolean(newickText.trim());
  const canRenderLineage = hasLineage && !!lineagePlot;
  const [activeTab, setActiveTab] = useState<"lineage" | "phylogeny">("lineage");

  useEffect(() => {
    if (!canRenderLineage && hasNewick) {
      setActiveTab("phylogeny");
      return;
    }
    if (canRenderLineage && !hasNewick) {
      setActiveTab("lineage");
    }
  }, [canRenderLineage, hasNewick]);

  const phyloAnnotations = useMemo(() => {
    if (!nodeAttributes) return [];
    return Object.entries(nodeAttributes).map(([label, attrs]) => ({ label, ...(attrs ?? {}) }));
  }, [nodeAttributes]);

  return (
    <Card className="flex h-full min-w-[500px] w-[min(92vw,680px)] shrink-0 flex-col">
      <CardHeader className="border-b pb-3">
        <CardTitle className="text-base flex items-center gap-1.5">
          {treeRef.title}
          {treeRef.title.startsWith("Sequence Trace") && <SequenceTraceInfoIcon />}
        </CardTitle>
        <p className="text-xs text-muted-foreground">
          {status?.method_id ?? "—"} · {status?.status ?? "—"} · {treeStatusLabel(tree, resolvedTreeIndex)}
        </p>
      </CardHeader>
      <CardContent className="flex flex-1 min-h-0 flex-col gap-3 pt-4">
        {(statusLoading || treesLoading || payloadLoading) && (
          <div className="flex items-center gap-2 rounded border p-4 text-sm text-muted-foreground">
            <Spinner className="shrink-0" />
            Loading tree…
          </div>
        )}

        {!statusLoading && status && !done && (
          <p className="rounded border p-3 text-sm text-muted-foreground">
            Run status is <strong>{status.status}</strong>. Expanded view is available once the run is DONE.
          </p>
        )}

        {!statusLoading && done && trees.length === 0 && (
          <p className="rounded border p-3 text-sm text-muted-foreground">No trees are available for this run.</p>
        )}

        {!payloadLoading && (canRenderLineage || hasNewick) && (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b pb-2">
              {canRenderLineage && (
                <button
                  type="button"
                  className={`rounded border px-2 py-1 text-xs ${
                    activeTab === "lineage" ? "bg-muted font-medium" : ""
                  }`}
                  onClick={() => setActiveTab("lineage")}
                >
                  Lineage
                </button>
              )}
              {hasNewick && (
                <button
                  type="button"
                  className={`rounded border px-2 py-1 text-xs ${
                    activeTab === "phylogeny" ? "bg-muted font-medium" : ""
                  }`}
                  onClick={() => setActiveTab("phylogeny")}
                >
                  Phylogeny
                </button>
              )}
            </div>

            <TreeZoomPane
              className="flex-1 min-h-[520px]"
              fitKey={`${treeRef.panelId}:${treeRef.runId}:${treeId ?? "pending"}:${activeTab}`}
            >
              <div className="min-h-[460px] rounded-md bg-background p-2">
                {activeTab === "lineage" && canRenderLineage && lineagePlot && (
                  <LineageSVG
                    lineagePlot={lineagePlot}
                    nodeAttributes={nodeAttributes}
                    displayIdField={displayIdField || undefined}
                    showLabels={showLabels}
                    filename={`comparison-expand-${treeRef.runId}-${treeId}`}
                    newickText={newickText || undefined}
                    highlightText={highlightText || undefined}
                  />
                )}
                {activeTab === "phylogeny" && hasNewick && (
                  <TreeSVG
                    newick={newickText}
                    annotations={phyloAnnotations}
                    showLabels={showLabels}
                    displayIdField={displayIdField || undefined}
                    highlightText={highlightText || undefined}
                    filename={`comparison-expand-${treeRef.runId}-${treeId}`}
                  />
                )}
              </div>
            </TreeZoomPane>
          </>
        )}

        {!payloadLoading && done && tree && !canRenderLineage && !hasNewick && (
          <p className="rounded border p-3 text-sm text-muted-foreground">
            No lineage plot or Newick is available for this tree.
          </p>
        )}
      </CardContent>
    </Card>
  );
});

export default function CompareExpandDialog({
  open,
  onOpenChange,
  trees,
  highlightText,
  displayIdField,
  showLabels,
}: CompareExpandDialogProps) {
  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        onOpenChange(false);
      }
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onOpenChange, open]);

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 bg-black/60 p-3 sm:p-5"
      role="dialog"
      aria-modal="true"
      onMouseDown={() => onOpenChange(false)}
    >
      <div
        className="mx-auto flex h-full w-full max-w-[99vw] flex-col rounded-lg border bg-background shadow-xl"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b px-4 py-3">
          <div className="space-y-1">
            <div className="flex items-center gap-1.5">
              <h3 className="text-base font-semibold">Expanded Sequence Trace gallery</h3>
              <SequenceTraceInfoIcon />
            </div>
            <p className="text-xs text-muted-foreground">
              {trees.length} tree{trees.length === 1 ? "" : "s"} shown from the current panel.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => onOpenChange(false)}
            aria-label="Close expanded Sequence Trace"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        <div className="flex-1 overflow-auto p-4">
          {trees.length === 0 ? (
            <p className="text-sm text-muted-foreground">No trees are currently selected in this Sequence Trace panel.</p>
          ) : (
            <div className="flex h-full min-h-0 items-stretch gap-4 overflow-x-auto pb-2">
              {trees.map((treeRef) => (
                <ExpandTreeTile
                  key={treeRef.panelId}
                  open={open}
                  treeRef={treeRef}
                  highlightText={highlightText}
                  displayIdField={displayIdField}
                  showLabels={showLabels}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
