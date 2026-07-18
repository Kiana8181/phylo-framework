"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import { ChevronLeft, ChevronRight, Maximize2, Settings2 } from "lucide-react";
import { RunsApi } from "@/features/runs/api";
import {
  type LineagePlot,
  type RunTree,
  type RunTreePayload,
} from "@phylo/contracts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Button } from "@/components/ui/button";
import TreeSettingsPanel from "@/components/phylo/tree/TreeSettingsPanel";
import TreeViewport from "@/components/phylo/tree/TreeViewport";
import TreeOverlay from "@/components/phylo/tree/TreeOverlay";
import { collectColorFields } from "@/components/phylo/tree/core";
import type { CollapseSignal } from "@/components/phylo/tree/TreeView";

const VIEW_LABELS: Record<"method" | "phylogeny" | "lineage", string> = {
  method: "Method output",
  phylogeny: "Phylogenetic tree",
  lineage: "Lineage tree",
};

const TIP_SIZE_FIELD = "abundance";

type TreesCarouselProps = {
  runId?: string | null;
  trees: Array<RunTree | string>;
  cleanNewick: (s: string) => string;
  colorBy?: string;
  unknownValue?: string;
  showInternalNodesDefault?: boolean;
};

export type TreeVM = {
  id: string;
  cloneId?: string;
  phylogenyNewick: string;
  hasServiceImage: boolean;
  hasLineagePlot: boolean;
  loadError?: string;
  isLoading?: boolean;
  /** Artifact id of the method-rendered image, served via the preview endpoint. */
  imageArtifactId?: string | null;
  nodeAttributes?: Record<string, Record<string, any>>;
  lineagePlot?: LineagePlot;
};

function treeIdFor(tree: RunTree | string, index: number): string {
  if (typeof tree === "string") return `tree-${index + 1}`;
  return tree.id || `tree-${index + 1}`;
}

// Per-tree heavyweight payloads (newick, node_attributes, lineage_plot,
// image_artifact_id) live in run_trees and are fetched on demand via
// RunsApi.tree. The slim result.trees entries don't carry them, so we no
// longer short-circuit the per-tree fetch on "embedded" hints.

function treeLabel(treeIdx: number, cloneId?: string): string {
  const cloneText = String(cloneId ?? "").trim();
  if (!cloneText) return `Tree ${treeIdx + 1}`;
  return `Tree ${treeIdx + 1} (clone ${cloneText})`;
}

export default function TreesCarousel({
  runId,
  trees,
  cleanNewick,
  colorBy,
  unknownValue,
  showInternalNodesDefault = false,
}: TreesCarouselProps) {
  const total = trees?.length ?? 0;
  const [idx, setIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<"method" | "phylogeny" | "lineage">("phylogeny");
  const [showLabels, setShowLabels] = useState(true);
  const [showInternalNodes, setShowInternalNodes] = useState(showInternalNodesDefault);
  const [showNodeNumbers, setShowNodeNumbers] = useState(showInternalNodesDefault);
  const [displayIdField, setDisplayIdField] = useState<string>("sequence_id");
  const [treeCache, setTreeCache] = useState<Record<string, RunTreePayload>>({});
  const [loadingTreeId, setLoadingTreeId] = useState<string | null>(null);
  const [treeLoadErrors, setTreeLoadErrors] = useState<Record<string, string>>({});
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [expandOpen, setExpandOpen] = useState(false);
  const [collapseSignal, setCollapseSignal] = useState<CollapseSignal>(null);
  const [colorByField, setColorByField] = useState<string>("auto");

  const canPrev = idx > 0;
  const canNext = idx < Math.max(0, total - 1);

  useEffect(() => {
    setIdx(0);
    setTreeCache({});
    setTreeLoadErrors({});
    setLoadingTreeId(null);
  }, [runId]);

  useEffect(() => {
    if (idx <= Math.max(0, total - 1)) return;
    setIdx(Math.max(0, total - 1));
  }, [idx, total]);

  const currentRawTree = trees?.[idx];

  useEffect(() => {
    if (!runId || !currentRawTree || typeof currentRawTree === "string") return;
    const treeId = treeIdFor(currentRawTree, idx);
    if (!treeId) return;
    // Use `in` rather than a truthiness check: a falsy-but-cached payload
    // (e.g. null) must still short-circuit, otherwise the effect would
    // refetch forever (each refetch creates a new treeCache reference,
    // re-triggering this effect via its dependency array).
    if (treeId in treeCache) return;

    let cancelled = false;
    setLoadingTreeId(treeId);
    setTreeLoadErrors((prev) => {
      if (!(treeId in prev)) return prev;
      const next = { ...prev };
      delete next[treeId];
      return next;
    });

    RunsApi.tree(runId, treeId)
      .then((payload) => {
        if (cancelled) return;
        if (!payload) {
          setTreeLoadErrors((prev) => ({ ...prev, [treeId]: "Failed to load tree data." }));
          return;
        }
        setTreeCache((prev) => ({ ...prev, [treeId]: payload }));
      })
      .catch((err: any) => {
        if (cancelled) return;
        const message =
          typeof err?.message === "string"
            ? err.message
            : typeof err === "string"
            ? err
            : "Failed to load tree data.";
        setTreeLoadErrors((prev) => ({ ...prev, [treeId]: message }));
      })
      .finally(() => {
        if (cancelled) return;
        setLoadingTreeId((prev) => (prev === treeId ? null : prev));
      });

    return () => {
      cancelled = true;
    };
  }, [currentRawTree, idx, runId, treeCache]);

  useEffect(() => {
    setShowInternalNodes(showInternalNodesDefault);
    setShowNodeNumbers(showInternalNodesDefault);
  }, [runId, showInternalNodesDefault]);

  const viewTrees = useMemo<TreeVM[]>(() => {
    // Per-tree heavyweight data (newick, node_attributes, lineage_plot,
    // image_artifact_id) is sourced exclusively from RunsApi.tree, cached in
    // treeCache. The slim result.trees array only provides the tree id and
    // clone id; the only fallback is when the active tree's payload hasn't
    // arrived yet, in which case the view shows a loading state.
    return (trees ?? []).map((t, i) => {
      const treeId = treeIdFor(t, i);
      const payload = treeCache[treeId];
      const lineagePlot = payload?.lineage_plot as LineagePlot | undefined;
      const imageArtifactId = payload?.image_artifact_id ?? null;
      const cloneId =
        typeof t !== "string" && typeof t.clone_id === "string" ? t.clone_id : undefined;
      const phylogenyNewick = payload?.newick
        ? cleanNewick(payload.original_newick || payload.newick || "")
        : "";
      return {
        id: treeId,
        cloneId,
        phylogenyNewick,
        hasServiceImage: Boolean(imageArtifactId),
        hasLineagePlot: Boolean(lineagePlot),
        isLoading: loadingTreeId === treeId,
        loadError: treeLoadErrors[treeId],
        imageArtifactId,
        nodeAttributes: payload?.node_attributes ?? {},
        lineagePlot,
      };
    });
  }, [cleanNewick, loadingTreeId, treeCache, treeLoadErrors, trees]);

  const current = viewTrees[idx];
  const isRenderableTreeTab = activeTab === "phylogeny" || activeTab === "lineage";
  const lineageDownloadName = current?.id || `tree-${idx + 1}`;
  const lineageNewick = current?.lineagePlot?.meta?.normalizedNewick ?? current?.phylogenyNewick ?? "";

  const tabs = useMemo(() => {
    if (!current) return [] as Array<"method" | "phylogeny" | "lineage">;
    const out: Array<"method" | "phylogeny" | "lineage"> = [];
    if (current.hasServiceImage) out.push("method");
    if (current.phylogenyNewick) out.push("phylogeny");
    if (current.hasLineagePlot) out.push("lineage");
    return out;
  }, [current]);

  useEffect(() => {
    if (!tabs.length) return;
    if (!tabs.includes(activeTab)) setActiveTab(tabs[0]);
  }, [activeTab, tabs]);

  const phyloAnnotations = useMemo((): Array<{ label: string } & Record<string, any>> => {
    if (!current?.nodeAttributes) return [];
    return Object.entries(current.nodeAttributes).map(([label, attrs]) => ({
      label,
      ...(attrs ?? {}),
    }));
  }, [current?.nodeAttributes]);

  // The field-key union used for BOTH the Display-ID and Colour-by options.
  const displayFields = useMemo(
    () => collectColorFields(current?.nodeAttributes, phyloAnnotations),
    [current?.nodeAttributes, phyloAnnotations],
  );

  // View-aware colour default: lineage → abundance; phylogeny → the stats field.
  const effectiveColorField =
    colorByField === "auto"
      ? activeTab === "lineage"
        ? "abundance"
        : colorBy ?? "abundance"
      : colorByField;
  const germlineLabel = current?.lineagePlot?.meta?.germlineLabel ?? null;

  useEffect(() => {
    if (!displayFields.length) return;
    if (!displayFields.includes(displayIdField)) setDisplayIdField(displayFields[0]);
  }, [displayFields, displayIdField]);

  const viewportProps = {
    activeTab,
    current,
    idx,
    phyloAnnotations,
    colorByField: effectiveColorField,
    germlineLabel,
    unknownValue,
    displayIdField,
    showLabels,
    showInternalNodes,
    showNodeNumbers,
    sizeByField: TIP_SIZE_FIELD,
    lineageDownloadName,
    lineageNewick,
    collapseSignal,
  };

  if (!total) {
    return (
      <Card className="p-4">
        <div className="text-sm text-muted-foreground">No trees returned.</div>
      </Card>
    );
  }

  return (
    <Card className="relative overflow-hidden p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b pb-2">
        <div className="flex flex-wrap items-center gap-2">
          {total > 1 && (
            <Select value={String(idx)} onValueChange={(v) => setIdx(Number(v))}>
              <SelectTrigger className="w-[200px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {viewTrees.map((tree, treeIdx) => (
                  <SelectItem key={tree.id} value={String(treeIdx)}>
                    {treeLabel(treeIdx, tree.cloneId)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}

          {tabs.length > 0 && (
            <Select value={activeTab} onValueChange={(v) => setActiveTab(v as typeof activeTab)}>
              <SelectTrigger className="w-[190px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {tabs.map((tab) => (
                  <SelectItem key={tab} value={tab}>
                    {VIEW_LABELS[tab]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </div>

        <div className="flex items-center gap-2">
          {tabs.length > 0 && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setExpandOpen(true)}
            >
              <Maximize2 className="size-4" />
              Expand
            </Button>
          )}
          {isRenderableTreeTab && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setSettingsOpen(true)}
            >
              <Settings2 className="size-4" />
              Settings
            </Button>
          )}
        </div>
      </div>

      <div className="flex items-center justify-between gap-3">
        <button
          className="rounded border px-3 py-1.5 text-sm inline-flex items-center gap-1 disabled:opacity-50"
          onClick={() => canPrev && setIdx((v) => Math.max(0, v - 1))}
          disabled={!canPrev}
        >
          <ChevronLeft className="w-4 h-4" /> Prev
        </button>

        <div className="flex-1 overflow-auto space-y-3">
          <TreeViewport {...viewportProps} />
        </div>

        <button
          className="rounded border px-3 py-1.5 text-sm inline-flex items-center gap-1 disabled:opacity-50"
          onClick={() => canNext && setIdx((v) => Math.min(total - 1, v + 1))}
          disabled={!canNext}
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>

      <TreeSettingsPanel
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        showLabels={showLabels}
        setShowLabels={setShowLabels}
        showInternalControls={Boolean(current?.hasLineagePlot || showInternalNodesDefault)}
        showInternalNodes={showInternalNodes}
        setShowInternalNodes={setShowInternalNodes}
        showNodeNumbers={showNodeNumbers}
        setShowNodeNumbers={setShowNodeNumbers}
        displayFields={displayFields}
        displayIdField={displayIdField}
        setDisplayIdField={setDisplayIdField}
        colorFields={displayFields}
        colorByField={colorByField}
        setColorByField={setColorByField}
        onCollapseAll={() => setCollapseSignal({ type: "collapseAll", nonce: Date.now() })}
        onExpandAll={() => setCollapseSignal({ type: "expandAll", nonce: Date.now() })}
      />

      <TreeOverlay
        open={expandOpen}
        onClose={() => setExpandOpen(false)}
        size="full"
        title={`${VIEW_LABELS[activeTab]} — ${treeLabel(idx, current?.cloneId)}`}
      >
        <TreeViewport {...viewportProps} viewportHeight="78vh" />
      </TreeOverlay>
    </Card>
  );
}
