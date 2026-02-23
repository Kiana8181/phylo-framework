"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import LineageSVG from "@/components/LineageSVG";
import TreeSVG from "@/components/TreeSVG";
import { Switch } from "@/components/ui/switch";
import { RunsApi } from "@/features/runs/api";
import { useRunStatus } from "@/features/runs/hooks";
import type { RunSummary, LineagePlot } from "@phylo/contracts";
import { Loader2, Maximize2, Search, Plus, X } from "lucide-react";
import CompareExpandDialog, { type CompareExpandTreeRef } from "@/components/comparison/CompareExpandDialog";
import RunAutocomplete from "@/components/comparison/RunAutocomplete";

type RunTreeListItem = {
  treeId: string;
  treeIndex: number;
  hasLineagePlot: boolean;
  hasServiceImage: boolean;
};

function useRunTrees(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runTrees", runId],
    queryFn: () => RunsApi.trees(runId!),
    enabled: !!runId && enabled,
  });
}

function useSameDataset(runId: string | null, enabled: boolean) {
  return useQuery({
    queryKey: ["runSameDataset", runId],
    queryFn: () => RunsApi.sameDataset(runId!),
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

type ColumnRun = {
  runId: string;
  methodId: string;
  status: string;
  trees: RunTreeListItem[];
};

type ComparisonPanelState = {
  panelId: string;
  runId: string;
  treeIndex: number;
};

type ErrorWithResponseStatus = {
  message?: string;
  detail?: string;
  response?: {
    status?: number;
  };
};

function toErrorWithResponseStatus(value: unknown): ErrorWithResponseStatus {
  if (!value || typeof value !== "object") return {};
  const maybe = value as Record<string, unknown>;
  const response =
    maybe.response && typeof maybe.response === "object"
      ? (maybe.response as Record<string, unknown>)
      : undefined;
  return {
    message: typeof maybe.message === "string" ? maybe.message : undefined,
    detail: typeof maybe.detail === "string" ? maybe.detail : undefined,
    response: response ? { status: typeof response.status === "number" ? response.status : undefined } : undefined,
  };
}

function displayFieldsFromAttrs(nodeAttributes: Record<string, Record<string, unknown>> | undefined): string[] {
  if (!nodeAttributes) return [];
  const keySet = new Set<string>();
  for (const v of Object.values(nodeAttributes)) {
    if (!v || typeof v !== "object") continue;
    for (const key of Object.keys(v)) {
      if (key === "tooltip") continue;
      keySet.add(key);
    }
  }
  const options = Array.from(keySet).sort((a, b) => a.localeCompare(b, "en"));
  if (options.includes("sequence_id")) {
    return ["sequence_id", ...options.filter((k) => k !== "sequence_id")];
  }
  return options;
}

function ComparisonColumn({
  title,
  run,
  treeIndex,
  onTreeIndexChange,
  highlightText,
  displayIdField,
  onDisplayIdFieldChange,
  showLabels,
  onShowLabelsChange,
  isLoading,
  error,
  placeholder,
  onRemove,
  showRemove,
}: {
  title: string;
  run: ColumnRun | null;
  treeIndex: number;
  onTreeIndexChange: (i: number) => void;
  highlightText: string;
  displayIdField: string;
  onDisplayIdFieldChange: (v: string) => void;
  showLabels: boolean;
  onShowLabelsChange: (v: boolean) => void;
  isLoading?: boolean;
  error?: string | null;
  placeholder: React.ReactNode;
  onRemove?: () => void;
  showRemove?: boolean;
}) {
  const tree = run?.trees?.[treeIndex];
  const treeId = tree?.treeId ?? null;
  const { data: payload, isLoading: payloadLoading } = useTreePayload(
    run?.runId ?? null,
    treeId,
    !!run && !!treeId
  );
  const lineagePlot = payload?.lineage_plot as LineagePlot | undefined;
  const nodeAttributes = payload?.node_attributes ?? undefined;
  const newickText = payload?.original_newick ?? payload?.newick ?? "";
  const hasLineage = tree?.hasLineagePlot ?? false;
  const hasNewick = Boolean(newickText?.trim());
  const showLineage = hasLineage && (lineagePlot ?? payloadLoading);
  const displayFields = displayFieldsFromAttrs(nodeAttributes as Record<string, Record<string, unknown>> | undefined);
  const [activeTab, setActiveTab] = useState<"lineage" | "phylogeny">("lineage");
  useEffect(() => {
    if (!showLineage && hasNewick) setActiveTab("phylogeny");
  }, [showLineage, hasNewick]);
  const phyloAnnotations = useMemo(() => {
    if (!nodeAttributes) return [];
    return Object.entries(nodeAttributes).map(([label, attrs]) => ({ label, ...(attrs ?? {}) }));
  }, [nodeAttributes]);

  if (error) {
    return (
      <Card className="min-w-[280px] w-full">
        <CardHeader className="pb-2 flex flex-row items-start justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          {showRemove && onRemove && (
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onRemove} aria-label="Remove">
              <X className="h-4 w-4" />
            </Button>
          )}
        </CardHeader>
        <CardContent>
          <p className="text-sm text-destructive">{error}</p>
        </CardContent>
      </Card>
    );
  }

  if (!run) {
    return (
      <Card className="min-w-[280px] w-full">
        <CardHeader className="pb-2 flex flex-row items-start justify-between gap-2">
          <CardTitle className="text-base">{title}</CardTitle>
          {showRemove && onRemove && (
            <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onRemove} aria-label="Remove">
              <X className="h-4 w-4" />
            </Button>
          )}
        </CardHeader>
        <CardContent>{placeholder}</CardContent>
      </Card>
    );
  }

  return (
    <Card className="min-w-[280px] w-full flex flex-col">
      <CardHeader className="pb-2 flex flex-row items-start justify-between gap-2">
        <div className="min-w-0">
          <CardTitle className="text-base">{title}</CardTitle>
          <p className="text-xs text-muted-foreground truncate">
            {run.methodId} · {run.status}
          </p>
        </div>
        {showRemove && onRemove && (
          <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onRemove} aria-label="Remove">
            <X className="h-4 w-4" />
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-3 flex-1 flex flex-col min-h-0">
        {run.trees.length > 0 && (
          <div className="flex items-center gap-2">
            <Label className="text-xs shrink-0">Tree</Label>
            <Select value={String(treeIndex)} onValueChange={(v) => onTreeIndexChange(Number(v))}>
              <SelectTrigger className="w-[140px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {run.trees.map((t, i) => (
                  <SelectItem key={t.treeId} value={String(i)}>
                    {t.hasLineagePlot ? `Tree ${i + 1}` : `Tree ${i + 1} (no lineage)`}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}
        {payloadLoading && !lineagePlot && !newickText && (
          <div className="flex items-center gap-2 rounded border p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin shrink-0" />
            Loading tree…
          </div>
        )}
        {(showLineage || hasNewick) && (
          <>
            <div className="flex flex-wrap items-center gap-2 border-b pb-2">
              {showLineage && (
                <button
                  type="button"
                  className={`rounded px-2 py-1 text-xs border ${activeTab === "lineage" ? "bg-muted font-medium" : ""}`}
                  onClick={() => setActiveTab("lineage")}
                >
                  Lineage
                </button>
              )}
              {hasNewick && (
                <button
                  type="button"
                  className={`rounded px-2 py-1 text-xs border ${activeTab === "phylogeny" ? "bg-muted font-medium" : ""}`}
                  onClick={() => setActiveTab("phylogeny")}
                >
                  Phylogeny
                </button>
              )}
              <div className="ml-auto flex items-center gap-2">
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <Switch checked={showLabels} onCheckedChange={onShowLabelsChange} aria-label="Show labels" />
                  Labels
                </label>
                {displayFields.length > 0 && (
                  <Select value={displayIdField} onValueChange={onDisplayIdFieldChange}>
                    <SelectTrigger className="w-[130px] h-8 text-xs">
                      <SelectValue placeholder="ID field" />
                    </SelectTrigger>
                    <SelectContent>
                      {displayFields.map((f) => (
                        <SelectItem key={f} value={f}>
                          {f}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                )}
              </div>
            </div>
            <div className="flex-1 min-h-[380px] overflow-auto rounded border bg-background">
              {activeTab === "lineage" && showLineage && lineagePlot && (
                <LineageSVG
                  lineagePlot={lineagePlot}
                  nodeAttributes={nodeAttributes}
                  displayIdField={displayIdField || undefined}
                  showLabels={showLabels}
                  filename={`comparison-${run.runId}-${treeId}`}
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
                />
              )}
            </div>
          </>
        )}
        {run.trees.length > 0 && !hasLineage && !hasNewick && !payloadLoading && (
          <p className="text-sm text-muted-foreground">No lineage plot or Newick for this tree.</p>
        )}
        {run.trees.length === 0 && !isLoading && (
          <p className="text-sm text-muted-foreground">No trees in this run.</p>
        )}
      </CardContent>
    </Card>
  );
}

export default function ComparisonPage() {
  const searchParams = useSearchParams();
  const baseFromUrl = searchParams.get("baseRunId");

  const [baseRunIdInput, setBaseRunIdInput] = useState("");
  const [baseRunId, setBaseRunId] = useState<string | null>(null);
  const [comparisonPanels, setComparisonPanels] = useState<ComparisonPanelState[]>([]);
  const [baseTreeIndex, setBaseTreeIndex] = useState(0);
  const [highlightSequence, setHighlightSequence] = useState("");
  const [displayIdField, setDisplayIdField] = useState("sequence_id");
  const [showLabels, setShowLabels] = useState(true);
  const [expandOpen, setExpandOpen] = useState(false);
  const nextPanelIdRef = useRef(1);

  useEffect(() => {
    if (baseFromUrl && baseFromUrl.trim()) {
      setBaseRunId(baseFromUrl.trim());
      setBaseRunIdInput(baseFromUrl.trim());
    }
  }, [baseFromUrl]);

  const { data: baseStatus, isLoading: baseStatusLoading, isError: baseStatusError, error: baseStatusErr } = useRunStatus(baseRunId ?? undefined);
  const baseDone = baseStatus?.status === "DONE";
  const { data: baseTrees, isLoading: baseTreesLoading } = useRunTrees(baseRunId, baseDone);
  const { data: sameDatasetList } = useSameDataset(baseRunId, baseDone);

  const baseRun = useMemo<ColumnRun | null>(() => {
    if (!baseRunId || !baseStatus || !baseTrees?.trees) return null;
    return {
      runId: baseRunId,
      methodId: baseStatus.method_id ?? "—",
      status: baseStatus.status ?? "—",
      trees: baseTrees.trees,
    };
  }, [baseRunId, baseStatus, baseTrees]);

  const maxTrees = baseRun?.trees?.length ?? 0;
  useEffect(() => {
    setBaseTreeIndex((prev) => {
      if (maxTrees <= 0) return 0;
      return prev >= maxTrees ? maxTrees - 1 : prev;
    });
  }, [maxTrees]);

  // Stable IDs isolate each comparison panel's run/tree state.
  const createPanelId = useCallback((): string => {
    const nextId = nextPanelIdRef.current;
    nextPanelIdRef.current += 1;
    return `comparison-panel-${nextId}`;
  }, []);

  const loadBaseRun = useCallback(() => {
    const id = baseRunIdInput.trim();
    if (id) {
      setBaseRunId(id);
      setComparisonPanels([]);
      setBaseTreeIndex(0);
      setExpandOpen(false);
    }
  }, [baseRunIdInput]);

  const addComparison = useCallback(() => {
    setComparisonPanels((prev) => [
      ...prev,
      {
        panelId: createPanelId(),
        runId: "",
        treeIndex: 0,
      },
    ]);
  }, [createPanelId]);

  const setComparisonRun = useCallback((panelId: string, runId: string | null) => {
    setComparisonPanels((prev) =>
      prev.map((panel) =>
        panel.panelId === panelId
          ? {
              ...panel,
              runId: runId ?? "",
              treeIndex: 0,
            }
          : panel,
      ),
    );
  }, []);

  const setComparisonTreeIndex = useCallback((panelId: string, nextTreeIndex: number) => {
    setComparisonPanels((prev) =>
      prev.map((panel) => (panel.panelId === panelId ? { ...panel, treeIndex: nextTreeIndex } : panel)),
    );
  }, []);

  const removeComparisonPanel = useCallback((panelId: string) => {
    setComparisonPanels((prev) => prev.filter((panel) => panel.panelId !== panelId));
  }, []);

  const expandTrees = useMemo<CompareExpandTreeRef[]>(() => {
    const refs: CompareExpandTreeRef[] = [];
    if (baseRun) {
      refs.push({
        panelId: "base",
        title: "Base",
        runId: baseRun.runId,
        treeIndex: baseTreeIndex,
      });
    }
    comparisonPanels.forEach((panel, index) => {
      if (!panel.runId) return;
      refs.push({
        panelId: panel.panelId,
        title: `Comparison ${index + 1}`,
        runId: panel.runId,
        treeIndex: panel.treeIndex,
      });
    });
    return refs;
  }, [baseRun, baseTreeIndex, comparisonPanels]);

  const selectedComparisonIds = comparisonPanels
    .map((panel) => panel.runId.trim())
    .filter((runId): runId is string => !!runId);
  const sameDatasetOptions = sameDatasetList ?? [];
  const availableForSelect = sameDatasetOptions.filter(
    (r) => r.id !== baseRunId && !selectedComparisonIds.includes(r.id),
  );

  useEffect(() => {
    if (!expandOpen) return;
    if (expandTrees.length === 0) {
      setExpandOpen(false);
    }
  }, [expandOpen, expandTrees.length]);

  const baseStatusErrorLike = toErrorWithResponseStatus(baseStatusErr);
  const baseStatusErrorMessage =
    baseStatusError && baseStatusErr
      ? (typeof baseStatusErr === "string"
          ? baseStatusErr
          : baseStatusErrorLike.message ?? baseStatusErrorLike.detail ?? "Failed to load run")
      : null;
  const is404 =
    baseStatusError &&
    (baseStatusErrorLike.response?.status === 404 ||
      String(baseStatusErrorMessage ?? "").toLowerCase().includes("not found"));

  return (
    <main className="mx-auto max-w-[1600px] w-full p-4 sm:p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">
          Comparison
        </h1>
        <p className="text-muted-foreground text-sm mt-1">
          Compare lineage views of runs on the same dataset. Set a base model, then add one or more runs to compare.
        </p>
      </header>

      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Search className="h-4 w-4" />
            Search / highlight in trees
          </CardTitle>
          <p className="text-xs text-muted-foreground font-normal mt-1">
            Type a sequence_id or part of a label — matching nodes are highlighted in all comparison trees.
          </p>
        </CardHeader>
        <CardContent>
          <Input
            placeholder="e.g. sequence_id or label text…"
            value={highlightSequence}
            onChange={(e) => setHighlightSequence(e.target.value)}
            className="max-w-md"
          />
        </CardContent>
      </Card>

      {/* Base + comparison setup */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-end gap-3">
          <div className="space-y-1.5">
            <Label htmlFor="base-run-id">Base run</Label>
            <Input
              id="base-run-id"
              placeholder="Paste run ID or use Compare to from dashboard…"
              value={baseRunIdInput}
              onChange={(e) => setBaseRunIdInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && loadBaseRun()}
              className="w-72 font-mono text-sm"
            />
          </div>
          <Button onClick={loadBaseRun} disabled={!baseRunIdInput.trim() || baseStatusLoading}>
            {baseStatusLoading ? <Loader2 className="h-4 w-4 animate-spin" /> : "Load"}
          </Button>
          {baseDone && (
            <Button
              variant="outline"
              size="sm"
              onClick={addComparison}
              disabled={availableForSelect.length === 0 && comparisonPanels.every((panel) => !panel.runId)}
              className="gap-1.5"
            >
              <Plus className="h-4 w-4" />
              Add comparison
            </Button>
          )}
        </div>
        {baseDone && sameDatasetOptions.length === 0 && (
          <div className="rounded-lg border bg-muted/40 p-4 text-sm text-muted-foreground space-y-1">
            <p className="font-medium text-foreground">No other runs with the same input file</p>
            <p>
              To compare, run the <strong>same file</strong> again (same upload or same file from File management) with different parameters or another method (e.g. gctree, dowser). New runs will appear when you click &quot;Add comparison&quot;.
            </p>
            <p className="text-xs mt-2">
              Runs created before the comparison feature may not be linked to a file; run the file again to get linkable runs.
            </p>
          </div>
        )}
      </section>

      {/* Side-by-side: Base | Comparison 1 | Comparison 2 | … */}
      <section className="space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-medium">Side-by-side comparison</h2>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="gap-1.5"
            onClick={() => setExpandOpen(true)}
            disabled={expandTrees.length === 0}
          >
            <Maximize2 className="h-4 w-4" />
            Expand
          </Button>
        </div>
        <p className="text-sm text-muted-foreground">
          Each panel keeps its own tree selection. Choose a run in each comparison slot to view trees side-by-side.
        </p>
        <div
          className="grid gap-4 overflow-x-auto pb-2"
          style={{
            gridTemplateColumns: `repeat(${Math.max(1, 1 + comparisonPanels.length)}, minmax(280px, 1fr))`,
          }}
        >
          <ComparisonColumn
            title="Base"
            run={baseRun}
            treeIndex={baseTreeIndex}
            onTreeIndexChange={setBaseTreeIndex}
            highlightText={highlightSequence}
            displayIdField={displayIdField}
            onDisplayIdFieldChange={setDisplayIdField}
            showLabels={showLabels}
            onShowLabelsChange={setShowLabels}
            isLoading={baseStatusLoading || (baseDone && baseTreesLoading)}
            error={
              is404
                ? "Run not found. Check the run ID, open from Run history, or ensure you're logged in if the run is yours."
                : baseStatusErrorMessage
            }
            placeholder={
              <p className="text-sm text-muted-foreground">
                Enter a run ID above and click Load, or open this page from &quot;Compare to&quot; on a finished run.
              </p>
            }
          />
          {comparisonPanels.map((panel, index) => (
            <ComparisonSlot
              key={panel.panelId}
              index={index}
              runId={panel.runId}
              sameDatasetList={sameDatasetList ?? []}
              selectedIds={[baseRunId, ...comparisonPanels.map((candidate) => candidate.runId)].filter(
                (id): id is string => !!id,
              )}
              onSelect={(id) => setComparisonRun(panel.panelId, id)}
              onRemove={() => removeComparisonPanel(panel.panelId)}
              treeIndex={panel.treeIndex}
              onTreeIndexChange={(nextTreeIndex) => setComparisonTreeIndex(panel.panelId, nextTreeIndex)}
              highlightText={highlightSequence}
              displayIdField={displayIdField}
              onDisplayIdFieldChange={setDisplayIdField}
              showLabels={showLabels}
              onShowLabelsChange={setShowLabels}
            />
          ))}
        </div>
      </section>

      <CompareExpandDialog
        open={expandOpen}
        onOpenChange={setExpandOpen}
        trees={expandTrees}
        highlightText={highlightSequence}
        displayIdField={displayIdField}
        showLabels={showLabels}
      />
    </main>
  );
}

function RunLineageBlock({
  run,
  treeIndex,
  onTreeIndexChange,
  highlightText,
  displayIdField,
  onDisplayIdFieldChange,
  showLabels,
  onShowLabelsChange,
  isLoading,
}: {
  run: ColumnRun | null;
  treeIndex: number;
  onTreeIndexChange: (i: number) => void;
  highlightText: string;
  displayIdField: string;
  onDisplayIdFieldChange: (v: string) => void;
  showLabels: boolean;
  onShowLabelsChange: (v: boolean) => void;
  isLoading?: boolean;
}) {
  const tree = run?.trees?.[treeIndex];
  const treeId = tree?.treeId ?? null;
  const runId = run?.runId ?? null;
  const { data: payload, isLoading: payloadLoading } = useTreePayload(
    runId,
    treeId,
    !!run && !!treeId
  );
  const lineagePlot = payload?.lineage_plot as LineagePlot | undefined;
  const nodeAttributes = payload?.node_attributes ?? undefined;
  const newickText = payload?.original_newick ?? payload?.newick ?? "";
  const hasLineage = tree?.hasLineagePlot ?? false;
  const hasNewick = Boolean(newickText?.trim());
  const showLineage = hasLineage && (lineagePlot ?? payloadLoading);
  const [activeTab, setActiveTab] = useState<"lineage" | "phylogeny">("lineage");
  useEffect(() => {
    if (!showLineage && hasNewick) setActiveTab("phylogeny");
  }, [showLineage, hasNewick]);
  const displayFields = useMemo(
    () => displayFieldsFromAttrs(nodeAttributes as Record<string, Record<string, unknown>> | undefined),
    [nodeAttributes]
  );
  const phyloAnnotations = useMemo(() => {
    if (!nodeAttributes) return [];
    return Object.entries(nodeAttributes).map(([label, attrs]) => ({ label, ...(attrs ?? {}) }));
  }, [nodeAttributes]);

  if (!run) return null;

  return (
    <div className="space-y-3">
      {run.trees.length > 0 && (
        <div className="flex items-center gap-2">
          <Label className="text-xs shrink-0">Tree</Label>
          <Select value={String(treeIndex)} onValueChange={(v) => onTreeIndexChange(Number(v))}>
            <SelectTrigger className="w-[140px]">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {run.trees.map((t, i) => (
                <SelectItem key={t.treeId} value={String(i)}>
                  {t.hasLineagePlot ? `Tree ${i + 1}` : `Tree ${i + 1} (no lineage)`}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {payloadLoading && !lineagePlot && !newickText && (
        <div className="flex items-center gap-2 rounded border p-4 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin shrink-0" />
          Loading tree…
        </div>
      )}
      {(showLineage || hasNewick) && (
        <>
          <div className="flex flex-wrap items-center gap-2 border-b pb-2">
            {showLineage && (
              <button
                type="button"
                className={`rounded px-2 py-1 text-xs border ${activeTab === "lineage" ? "bg-muted font-medium" : ""}`}
                onClick={() => setActiveTab("lineage")}
              >
                Lineage
              </button>
            )}
            {hasNewick && (
              <button
                type="button"
                className={`rounded px-2 py-1 text-xs border ${activeTab === "phylogeny" ? "bg-muted font-medium" : ""}`}
                onClick={() => setActiveTab("phylogeny")}
              >
                Phylogeny
              </button>
            )}
            <div className="ml-auto flex items-center gap-2">
              <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <Switch checked={showLabels} onCheckedChange={onShowLabelsChange} aria-label="Show labels" />
                Labels
              </label>
              {displayFields.length > 0 && (
                <Select value={displayIdField} onValueChange={onDisplayIdFieldChange}>
                  <SelectTrigger className="w-[130px] h-8 text-xs">
                    <SelectValue placeholder="ID field" />
                  </SelectTrigger>
                  <SelectContent>
                    {displayFields.map((f) => (
                      <SelectItem key={f} value={f}>
                        {f}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </div>
          </div>
          <div className="min-h-[380px] overflow-auto rounded border bg-background">
            {activeTab === "lineage" && showLineage && lineagePlot && (
              <LineageSVG
                lineagePlot={lineagePlot}
                nodeAttributes={nodeAttributes}
                displayIdField={displayIdField || undefined}
                showLabels={showLabels}
                filename={`comparison-${run.runId}-${treeId}`}
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
              />
            )}
          </div>
        </>
      )}
      {run.trees.length > 0 && !hasLineage && !hasNewick && !payloadLoading && (
        <p className="text-sm text-muted-foreground">No lineage plot or Newick for this tree.</p>
      )}
      {run.trees.length === 0 && !isLoading && (
        <p className="text-sm text-muted-foreground">No trees in this run.</p>
      )}
    </div>
  );
}

function ComparisonSlot({
  index,
  runId,
  sameDatasetList,
  selectedIds,
  onSelect,
  onRemove,
  treeIndex,
  onTreeIndexChange,
  highlightText,
  displayIdField,
  onDisplayIdFieldChange,
  showLabels,
  onShowLabelsChange,
}: {
  index: number;
  runId: string;
  sameDatasetList: RunSummary[];
  selectedIds: string[];
  onSelect: (id: string | null) => void;
  onRemove: () => void;
  treeIndex: number;
  onTreeIndexChange: (i: number) => void;
  highlightText: string;
  displayIdField: string;
  onDisplayIdFieldChange: (v: string) => void;
  showLabels: boolean;
  onShowLabelsChange: (v: boolean) => void;
}) {
  const { data: status } = useRunStatus(runId || undefined);
  const done = status?.status === "DONE";
  const { data: trees, isLoading: treesLoading } = useRunTrees(runId || null, !!runId && done);

  const run: ColumnRun | null =
    runId && status && trees?.trees
      ? {
          runId,
          methodId: status.method_id ?? "—",
          status: status.status ?? "—",
          trees: trees.trees,
        }
      : null;

  const options = sameDatasetList.filter((r) => !selectedIds.includes(r.id) || r.id === runId);

  const runTreeCount = run?.trees.length ?? 0;
  const runIdentity = run?.runId ?? "";

  useEffect(() => {
    if (!runTreeCount) return;
    if (treeIndex >= runTreeCount) {
      onTreeIndexChange(runTreeCount - 1);
    }
  }, [onTreeIndexChange, runIdentity, runTreeCount, treeIndex]);

  return (
    <Card className="min-w-[280px] w-full flex flex-col">
      <CardHeader className="pb-2 flex flex-row items-start justify-between gap-2">
        <CardTitle className="text-base">Comparison {index + 1}</CardTitle>
        <Button variant="ghost" size="icon" className="h-8 w-8 shrink-0" onClick={onRemove} aria-label="Remove">
          <X className="h-4 w-4" />
        </Button>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="space-y-1.5">
          <Label>Same dataset run</Label>
          <RunAutocomplete
            value={runId || null}
            onChange={onSelect}
            options={options.map((r) => ({ id: r.id, method_id: r.method_id }))}
            placeholder="Select run…"
          />
        </div>
        {run ? (
          <RunLineageBlock
            run={run}
            treeIndex={treeIndex}
            onTreeIndexChange={onTreeIndexChange}
            highlightText={highlightText}
            displayIdField={displayIdField}
            onDisplayIdFieldChange={onDisplayIdFieldChange}
            showLabels={showLabels}
            onShowLabelsChange={onShowLabelsChange}
            isLoading={treesLoading}
          />
        ) : (
          <p className="text-sm text-muted-foreground">Choose a run above.</p>
        )}
      </CardContent>
    </Card>
  );
}
