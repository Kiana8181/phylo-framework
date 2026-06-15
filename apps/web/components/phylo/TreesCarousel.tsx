"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import TreeSVG from "@/components/TreeSVG";
import LineageSVG from "@/components/LineageSVG";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { RunsApi } from "@/features/runs/api";
import ArtifactImage from "@/components/phylo/ArtifactImage";
import {
  API_ROUTES,
  type LineagePlot,
  type RunTree,
  type RunTreePayload,
} from "@phylo/contracts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Loading } from "@/components/ui/loading";

type TreesCarouselProps = {
  runId?: string | null;
  trees: Array<RunTree | string>;
  cleanNewick: (s: string) => string;
  colorBy?: string;
  unknownValue?: string;
  tipSizeBy?: string;
  showInternalNodesDefault?: boolean;
};

type TreeVM = {
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
  tipSizeBy,
  showInternalNodesDefault = false,
}: TreesCarouselProps) {
  const total = trees?.length ?? 0;
  const [idx, setIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<"method" | "phylogeny" | "lineage">("phylogeny");
  const [showLabels, setShowLabels] = useState(true);
  const [showInternalNodes, setShowInternalNodes] = useState(showInternalNodesDefault);
  const [showNodeNumbers, setShowNodeNumbers] = useState(showInternalNodesDefault);
  const [displayIdField, setDisplayIdField] = useState<string>("sequence_id");
  const [sizeByField, setSizeByField] = useState<string>("");
  const [treeCache, setTreeCache] = useState<Record<string, RunTreePayload>>({});
  const [loadingTreeId, setLoadingTreeId] = useState<string | null>(null);
  const [treeLoadErrors, setTreeLoadErrors] = useState<Record<string, string>>({});

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

  const displayFields = useMemo(() => {
    const attrs = current?.nodeAttributes ?? {};
    const keySet = new Set<string>();
    for (const v of Object.values(attrs)) {
      if (!v || typeof v !== "object") continue;
      for (const key of Object.keys(v)) {
        if (["tooltip"].includes(key)) continue;
        keySet.add(key);
      }
    }
    for (const row of phyloAnnotations) {
      for (const [key, value] of Object.entries(row)) {
        if (["label", "final_tip_label"].includes(key)) continue;
        if (value != null && value !== "") keySet.add(key);
      }
    }
    const options = Array.from(keySet).sort((a, b) => a.localeCompare(b, "en"));
    if (options.includes("sequence_id")) {
      return ["sequence_id", ...options.filter((k) => k !== "sequence_id")];
    }
    return options;
  }, [current?.nodeAttributes, phyloAnnotations]);

  const sizeFields = useMemo(() => {
    const nums = new Set<string>();
    for (const row of phyloAnnotations) {
      for (const [key, value] of Object.entries(row)) {
        if (["label", "final_tip_label"].includes(key)) continue;
        const n = Number(value);
        if (Number.isFinite(n)) nums.add(key);
      }
    }
    return Array.from(nums).sort((a, b) => a.localeCompare(b, "en"));
  }, [phyloAnnotations]);

  useEffect(() => {
    if (!sizeFields.length) {
      setSizeByField("");
      return;
    }
    const preferred = tipSizeBy && sizeFields.includes(tipSizeBy) ? tipSizeBy : "";
    if (preferred) {
      setSizeByField(preferred);
      return;
    }
    if (sizeByField && sizeFields.includes(sizeByField)) return;
    setSizeByField("");
  }, [sizeFields, sizeByField, tipSizeBy, idx]);

  useEffect(() => {
    if (!displayFields.length) return;
    if (!displayFields.includes(displayIdField)) setDisplayIdField(displayFields[0]);
  }, [displayFields, displayIdField]);

  if (!total) {
    return (
      <Card className="p-4">
        <div className="text-sm text-muted-foreground">No trees returned.</div>
      </Card>
    );
  }

  return (
    <Card className="p-4 space-y-3">
      <div className="flex items-center justify-between">
        <h4 className="font-medium">Trees</h4>
        <div className="text-xs text-muted-foreground">
          {idx + 1} / {total}
        </div>
      </div>

      <div className="overflow-x-auto">
        <div className="flex min-w-max items-center gap-2">
          {viewTrees.map((tree, treeIdx) => (
            <button
              key={tree.id}
              className={`rounded border px-3 py-1 text-xs ${
                treeIdx === idx ? "bg-muted font-medium" : "bg-transparent"
              }`}
              onClick={() => setIdx(treeIdx)}
            >
              {treeLabel(treeIdx, tree.cloneId)}
            </button>
          ))}
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
          {tabs.length > 0 && (
            <div className="flex items-center gap-2 border-b pb-2">
              {tabs.map((tab) => (
                <button
                  key={tab}
                  className={`rounded px-3 py-1.5 text-sm border ${
                    activeTab === tab ? "bg-muted font-medium" : "bg-transparent"
                  }`}
                  onClick={() => setActiveTab(tab)}
                >
                  {tab === "method" && "Method Output"}
                  {tab === "phylogeny" && "Phylogeny"}
                  {tab === "lineage" && "Lineage"}
                </button>
              ))}

              {isRenderableTreeTab && (
                <div className="ml-auto flex items-center gap-4">
                  <label
                    className="flex items-center gap-2 text-xs text-muted-foreground"
                    title="Show tip or display labels on tree views"
                  >
                    <span>Show labels</span>
                    <Switch checked={showLabels} onCheckedChange={setShowLabels} aria-label="Show labels" />
                  </label>
                  {(current?.hasLineagePlot || showInternalNodesDefault) && (
                    <>
                      <label
                        className="flex items-center gap-2 text-xs text-muted-foreground"
                        title="Show reconstructed internal node labels on the lineage view"
                      >
                        <span>Internal nodes</span>
                        <Switch
                          checked={showInternalNodes}
                          onCheckedChange={setShowInternalNodes}
                          aria-label="Show internal nodes"
                        />
                      </label>
                      <label
                        className="flex items-center gap-2 text-xs text-muted-foreground"
                        title="Show Dowser/ape node index numbers on internal nodes"
                      >
                        <span>Node numbers</span>
                        <Switch
                          checked={showNodeNumbers}
                          onCheckedChange={setShowNodeNumbers}
                          aria-label="Show node numbers"
                        />
                      </label>
                    </>
                  )}

                  {displayFields.length > 0 && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">Display ID</span>
                      <Select value={displayIdField} onValueChange={setDisplayIdField}>
                        <SelectTrigger className="w-[180px]">
                          <SelectValue placeholder="Display field" />
                        </SelectTrigger>
                        <SelectContent>
                          {displayFields.map((f) => (
                            <SelectItem key={f} value={f}>
                              {f}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}

                  {sizeFields.length > 0 && (
                    <div className="flex items-center gap-2">
                      <span className="text-xs text-muted-foreground">Tip size by</span>
                      <Select
                        value={sizeByField || "__none__"}
                        onValueChange={(v) => setSizeByField(v === "__none__" ? "" : v)}
                      >
                        <SelectTrigger className="w-[180px]">
                          <SelectValue placeholder="Constant size" />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="__none__">Constant size</SelectItem>
                          {sizeFields.map((f) => (
                            <SelectItem key={f} value={f}>
                              {f}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {activeTab === "method" && current?.imageArtifactId && (
            <div className="overflow-hidden rounded border bg-white">
              <ArtifactImage
                previewUrl={API_ROUTES.artifactPreview(current.imageArtifactId)}
                alt={`Method output tree ${idx + 1}`}
                className="w-full h-auto mx-auto"
              />
            </div>
          )}
          {activeTab === "method" && !current?.imageArtifactId && current?.isLoading && (
            <Loading
              illustration="dna"
              label="Loading tree image..."
              className="rounded border p-4 py-8"
            />
          )}
          {activeTab === "method" && !current?.imageArtifactId && !current?.isLoading && current?.loadError && (
            <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
          )}
          {activeTab === "method" && !current?.imageArtifactId && !current?.isLoading && !current?.loadError && (
            <div className="rounded border p-4 text-sm text-muted-foreground">No method output available.</div>
          )}

          {activeTab === "phylogeny" && current?.phylogenyNewick && (
            <TreeSVG
              newick={current.phylogenyNewick}
              annotations={phyloAnnotations}
              showLabels={showLabels}
              showInternalNodes={showInternalNodes}
              showNodeNumbers={showNodeNumbers}
              colorBy={colorBy}
              unknownValue={unknownValue}
              displayIdField={displayIdField || undefined}
              sizeBy={sizeByField || undefined}
            />
          )}

          {activeTab === "lineage" && current?.lineagePlot && (
            <LineageSVG
              lineagePlot={current.lineagePlot}
              nodeAttributes={current.nodeAttributes}
              displayIdField={displayIdField || undefined}
              showLabels={showLabels}
              showInternalNodes={showInternalNodes}
              showNodeNumbers={showNodeNumbers}
              filename={lineageDownloadName}
              newickText={lineageNewick}
            />
          )}
          {activeTab === "lineage" && !current?.lineagePlot && current?.isLoading && (
            <div className="rounded border p-4 text-sm text-muted-foreground">Loading lineage plot...</div>
          )}
          {activeTab === "lineage" && !current?.lineagePlot && !current?.isLoading && current?.loadError && (
            <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
          )}
          {activeTab === "lineage" && !current?.lineagePlot && !current?.isLoading && !current?.loadError && (
            <div className="rounded border p-4 text-sm text-muted-foreground">No lineage plot available.</div>
          )}
        </div>

        <button
          className="rounded border px-3 py-1.5 text-sm inline-flex items-center gap-1 disabled:opacity-50"
          onClick={() => canNext && setIdx((v) => Math.min(total - 1, v + 1))}
          disabled={!canNext}
        >
          Next <ChevronRight className="w-4 h-4" />
        </button>
      </div>
    </Card>
  );
}
