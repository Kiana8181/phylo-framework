"use client";

import { memo, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Crosshair, X } from "lucide-react";
import { Spinner } from "@/components/ui/loading";
import type { LineagePlot, RunTreeListItem, TreeNodeAttrs } from "@phylo/contracts";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { RunsApi } from "@/features/runs/api";
import LineageSVG from "@/components/LineageSVG";
import TreeZoomPane, { type TreeZoomPaneHandle } from "@/components/comparison/TreeZoomPane";
import SequenceTraceInfoIcon from "@/components/sequence-trace/SequenceTraceInfoIcon";

/** Zoom level applied when "Show me" centers on a matched node. */
const FOCUS_SCALE = 2.5;

export type CompareExpandTreeRef = {
  panelId: string;
  runId: string;
  treeIndex: number;
};

type CompareExpandDialogProps = {
  open: boolean;
  onOpenChange: (nextOpen: boolean) => void;
  trees: CompareExpandTreeRef[];
  /** Initial search text seeded from the page when the dialog opens. */
  highlightText: string;
  displayIdField: string;
  methodNameById: Map<string, string>;
};

type ExpandTreeTileProps = {
  open: boolean;
  treeRef: CompareExpandTreeRef;
  highlightText: string;
  displayIdField: string;
  markMatches: boolean;
  focusSignal: number;
  methodNameById: Map<string, string>;
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
  markMatches,
  focusSignal,
  methodNameById,
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
  const canRenderLineage = (tree?.hasLineagePlot ?? false) && !!lineagePlot;

  const methodId = status?.method_id ?? "";
  const methodTitle = (methodId && (methodNameById.get(methodId) ?? methodId)) || "—";

  const zoomRef = useRef<TreeZoomPaneHandle>(null);

  return (
    <Card className="flex w-[min(92vw,680px)] shrink-0 flex-col">
      <CardHeader className="border-b pb-3">
        <CardTitle className="text-base">{methodTitle}</CardTitle>
        <p className="text-xs text-muted-foreground">
          {treeStatusLabel(tree, resolvedTreeIndex)} · {status?.status ?? "—"}
        </p>
      </CardHeader>
      <CardContent className="flex flex-col gap-3 pt-4">
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

        {!payloadLoading && canRenderLineage && lineagePlot && (
          <div className="h-[70vh]">
            <TreeZoomPane ref={zoomRef} className="h-full" fitKey={`${treeRef.panelId}:${treeId}`}>
              <LineageSVG
                lineagePlot={lineagePlot}
                nodeAttributes={nodeAttributes}
                displayIdField={displayIdField || undefined}
                filename={`comparison-expand-${treeRef.runId}-${treeId}`}
                newickText={newickText || undefined}
                highlightText={highlightText || undefined}
                markMatches={markMatches}
                focusSignal={focusSignal}
                fitToParent
                onRequestFocus={(x, y) => zoomRef.current?.focusOnPoint(x, y, FOCUS_SCALE)}
              />
            </TreeZoomPane>
          </div>
        )}

        {!payloadLoading && done && tree && !canRenderLineage && (
          <p className="rounded border p-3 text-sm text-muted-foreground">
            No lineage plot is available for this tree.
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
  methodNameById,
}: CompareExpandDialogProps) {
  const [query, setQuery] = useState(highlightText);
  const [mark, setMark] = useState(false);
  const [focus, setFocus] = useState(0);

  useEffect(() => {
    if (!open) return;
    // Seed the in-dialog search from the page's current text each time it opens.
    setQuery(highlightText);
    setMark(false);
  }, [open, highlightText]);

  useEffect(() => {
    if (!open) return;
    const prevOverflow = document.body.style.overflow;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onOpenChange(false);
    };
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.body.style.overflow = prevOverflow;
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [onOpenChange, open]);

  if (!open) return null;

  const showMe = () => {
    if (!query.trim()) return;
    setMark(true);
    setFocus((n) => n + 1);
  };

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
        <div className="flex flex-wrap items-center justify-between gap-3 border-b px-4 py-3">
          <div className="flex items-center gap-1.5">
            <h3 className="text-base font-semibold">Expanded Sequence Trace gallery</h3>
            <SequenceTraceInfoIcon />
          </div>
          <div className="flex flex-1 flex-wrap items-center justify-end gap-2">
            <Input
              placeholder="sequence_id or label…"
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setMark(false);
              }}
              onKeyDown={(e) => e.key === "Enter" && showMe()}
              className="max-w-xs"
            />
            <Button type="button" onClick={showMe} disabled={!query.trim()} className="gap-1.5">
              <Crosshair className="h-4 w-4" />
              Show me
            </Button>
            {(query || mark) && (
              <Button
                type="button"
                variant="ghost"
                onClick={() => {
                  setQuery("");
                  setMark(false);
                }}
              >
                Clear
              </Button>
            )}
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
        </div>

        <div className="flex-1 overflow-auto p-4">
          {trees.length === 0 ? (
            <p className="text-sm text-muted-foreground">No trees are currently selected in this Sequence Trace panel.</p>
          ) : (
            <div className="flex items-start gap-4 overflow-x-auto pb-2">
              {trees.map((treeRef) => (
                <ExpandTreeTile
                  key={treeRef.panelId}
                  open={open}
                  treeRef={treeRef}
                  highlightText={query}
                  displayIdField={displayIdField}
                  markMatches={mark}
                  focusSignal={focus}
                  methodNameById={methodNameById}
                />
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
