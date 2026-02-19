"use client";

import { useEffect, useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import TreeSVG from "@/components/TreeSVG";
import LineageSVG from "@/components/LineageSVG";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { RunsApi } from "@/features/runs/api";
import type {
  FigurePayload,
  LineagePlot,
  RunTree,
  RunTreePayload,
  TreeServiceImage,
} from "@phylo/contracts";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

type TreesCarouselProps = {
  runId?: string | null;
  trees: Array<RunTree | string>;
  figures?: FigurePayload;
  annotations?: Array<Array<Record<string, any>> | null>;
  cleanNewick: (s: string) => string;
  colorBy?: string;
  unknownValue?: string;
};

type TreeImage = {
  mime: string;
  base64: string;
};

type TreeVM = {
  id: string;
  phylogenyNewick: string;
  hasServiceImage: boolean;
  hasLineagePlot: boolean;
  loadError?: string;
  isLoading?: boolean;
  serviceImage?: TreeImage;
  nodeAttributes?: Record<string, Record<string, any>>;
  lineagePlot?: LineagePlot;
};

function toImagePayload(raw?: string | null): TreeImage | undefined {
  if (!raw) return undefined;
  const txt = String(raw).trim();
  if (!txt) return undefined;
  const m = txt.match(/^data:([^;]+);base64,(.+)$/i);
  if (m) return { mime: m[1], base64: m[2] };
  return { mime: "image/png", base64: txt };
}

function fromServiceImage(raw?: TreeServiceImage | null): TreeImage | undefined {
  if (!raw?.base64) return undefined;
  return { mime: raw.mime || "image/png", base64: raw.base64 };
}

function buildAnnoMapFromRows(rows?: Array<Record<string, any>> | null): Record<string, Record<string, any>> {
  const out: Record<string, Record<string, any>> = {};
  if (!Array.isArray(rows)) return out;
  for (const row of rows) {
    const label = String(row?.label ?? "").trim();
    if (!label) continue;
    const item = { ...row };
    delete item.label;
    out[label] = item;
  }
  return out;
}

function treeIdFor(tree: RunTree | string, index: number): string {
  if (typeof tree === "string") return `tree-${index + 1}`;
  return tree.id || `tree-${index + 1}`;
}

function hasEmbeddedPayload(tree: RunTree): boolean {
  return Boolean(
    tree.lineage_plot ||
      tree.node_attributes ||
      tree.label_to_sequence_id ||
      tree.visualizations?.service_image
  );
}

export default function TreesCarousel({
  runId,
  trees,
  figures,
  annotations,
  cleanNewick,
  colorBy,
  unknownValue,
}: TreesCarouselProps) {
  const total = trees?.length ?? 0;
  const [idx, setIdx] = useState(0);
  const [activeTab, setActiveTab] = useState<"method" | "phylogeny" | "lineage">("phylogeny");
  const [showLabels, setShowLabels] = useState(true);
  const [displayIdField, setDisplayIdField] = useState<string>("sequence_id");
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
    if (treeCache[treeId]) return;
    if (hasEmbeddedPayload(currentRawTree)) return;

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

  const viewTrees = useMemo<TreeVM[]>(() => {
    return (trees ?? []).map((t, i) => {
      if (typeof t === "string") {
        const figureImage = toImagePayload(figures?.phylogeny?.[i]);
        return {
          id: `tree-${i + 1}`,
          phylogenyNewick: cleanNewick(t),
          hasServiceImage: Boolean(figureImage?.base64),
          hasLineagePlot: false,
          isLoading: false,
          loadError: undefined,
          serviceImage: figureImage,
          nodeAttributes: buildAnnoMapFromRows(annotations?.[i]),
        };
      }

      const treeId = treeIdFor(t, i);
      const payload = treeCache[treeId];
      const svcImage =
        fromServiceImage(payload?.service_image) ??
        fromServiceImage(t.visualizations?.service_image) ??
        toImagePayload(figures?.phylogeny?.[i]);
      const attrs =
        payload?.node_attributes ??
        t.node_attributes ??
        buildAnnoMapFromRows(annotations?.[i]);
      const lineagePlot = (payload?.lineage_plot ?? t.lineage_plot) as LineagePlot | undefined;
      return {
        id: treeId,
        phylogenyNewick: cleanNewick(t.original_newick || t.newick || ""),
        hasServiceImage: Boolean(t.has_service_image || svcImage?.base64),
        hasLineagePlot: Boolean(t.has_lineage_plot || lineagePlot),
        isLoading: loadingTreeId === treeId,
        loadError: treeLoadErrors[treeId],
        serviceImage: svcImage,
        nodeAttributes: attrs,
        lineagePlot,
      };
    });
  }, [annotations, cleanNewick, figures?.phylogeny, loadingTreeId, treeCache, treeLoadErrors, trees]);

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

  const phyloAnnotations = useMemo(() => {
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
    const options = Array.from(keySet).sort((a, b) => a.localeCompare(b, "en"));
    if (options.includes("sequence_id")) {
      return ["sequence_id", ...options.filter((k) => k !== "sequence_id")];
    }
    return options;
  }, [current?.nodeAttributes]);

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
              Tree {treeIdx + 1}
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
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <span>Show labels</span>
                    <Switch checked={showLabels} onCheckedChange={setShowLabels} aria-label="Show labels" />
                  </label>

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
                </div>
              )}
            </div>
          )}

          {activeTab === "method" && current?.serviceImage?.base64 && (
            <div className="overflow-hidden rounded border bg-white">
              <img
                src={`data:${current.serviceImage.mime};base64,${current.serviceImage.base64}`}
                alt={`Method output tree ${idx + 1}`}
                className="w-full h-auto mx-auto"
              />
            </div>
          )}
          {activeTab === "method" && !current?.serviceImage?.base64 && current?.isLoading && (
            <div className="rounded border p-4 text-sm text-muted-foreground">Loading tree image...</div>
          )}
          {activeTab === "method" && !current?.serviceImage?.base64 && !current?.isLoading && current?.loadError && (
            <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
          )}
          {activeTab === "method" && !current?.serviceImage?.base64 && !current?.isLoading && !current?.loadError && (
            <div className="rounded border p-4 text-sm text-muted-foreground">No method output available.</div>
          )}

          {activeTab === "phylogeny" && current?.phylogenyNewick && (
            <TreeSVG
              newick={current.phylogenyNewick}
              annotations={phyloAnnotations}
              showLabels={showLabels}
              colorBy={colorBy}
              unknownValue={unknownValue}
              displayIdField={displayIdField || undefined}
            />
          )}

          {activeTab === "lineage" && current?.lineagePlot && (
            <LineageSVG
              lineagePlot={current.lineagePlot}
              nodeAttributes={current.nodeAttributes}
              displayIdField={displayIdField || undefined}
              showLabels={showLabels}
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
