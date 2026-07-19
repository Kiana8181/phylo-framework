"use client";

import { API_ROUTES } from "@phylo/contracts";
import TreeView, { type CollapseSignal } from "@/components/phylo/tree/TreeView";
import TreeSkeleton from "@/components/phylo/tree/TreeSkeleton";
import ArtifactImage from "@/components/phylo/ArtifactImage";
import { Loading } from "@/components/ui/loading";
import type { TreeVM } from "@/components/phylo/TreesCarousel";

export type TreeViewportProps = {
  activeTab: "method" | "phylogeny" | "lineage";
  current?: TreeVM;
  idx: number;
  phyloAnnotations: Array<{ label: string } & Record<string, unknown>>;
  /** Resolved colour-by field (view-aware default already applied by the caller). */
  colorByField: string | null;
  colorDomain?: readonly string[] | null;
  germlineLabel?: string | null;
  unknownValue?: string;
  displayIdField: string;
  showLabels: boolean;
  showInternalNodes: boolean;
  showNodeNumbers: boolean;
  sizeByField: string;
  lineageDownloadName: string;
  lineageNewick: string;
  collapseSignal?: CollapseSignal;
  /** Height for the interactive tree pane (fullscreen expand passes e.g. "78vh"). */
  viewportHeight?: number | string;
};

/** Renders the active tree view (method image / phylogeny / lineage), with its
 *  loading / error / empty states. Shared by the inline display and the
 *  fullscreen expand dialog. The phylogeny/lineage tabs render the single
 *  `TreeView`; the method tab is untouched. */
export default function TreeViewport({
  activeTab,
  current,
  idx,
  phyloAnnotations,
  colorByField,
  colorDomain,
  germlineLabel,
  unknownValue,
  displayIdField,
  showLabels,
  showInternalNodes,
  showNodeNumbers,
  sizeByField,
  lineageDownloadName,
  lineageNewick,
  collapseSignal,
  viewportHeight,
}: TreeViewportProps) {
  return (
    <>
      {activeTab === "method" && current?.imageArtifactId && (
        <div className="overflow-hidden rounded border bg-white">
          <ArtifactImage
            previewUrl={API_ROUTES.artifactPreview(current.imageArtifactId)}
            alt={`Method output tree ${idx + 1}`}
            className="mx-auto h-auto w-full"
          />
        </div>
      )}
      {activeTab === "method" && !current?.imageArtifactId && current?.isLoading && (
        <Loading illustration="dna" label="Loading tree image..." className="rounded border p-4 py-8" />
      )}
      {activeTab === "method" && !current?.imageArtifactId && !current?.isLoading && current?.loadError && (
        <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
      )}
      {activeTab === "method" && !current?.imageArtifactId && !current?.isLoading && !current?.loadError && (
        <div className="rounded border p-4 text-sm text-muted-foreground">No method output available.</div>
      )}

      {activeTab === "phylogeny" && current?.phylogenyNewick && (
        <TreeView
          source={{ kind: "phylogeny", newick: current.phylogenyNewick, annotations: phyloAnnotations }}
          showLabels={showLabels}
          showInternalNodes={showInternalNodes}
          showNodeNumbers={showNodeNumbers}
          colorByField={colorByField}
          colorDomain={colorDomain}
          germlineLabel={germlineLabel}
          unknownValue={unknownValue}
          displayIdField={displayIdField || undefined}
          sizeBy={sizeByField || undefined}
          filename={current.id || `tree-${idx + 1}`}
          displayNewick={current.displayNewick}
          collapseSignal={collapseSignal}
          height={viewportHeight}
        />
      )}
      {activeTab === "phylogeny" && !current?.phylogenyNewick && current?.isLoading && (
        <TreeSkeleton height={viewportHeight} />
      )}
      {activeTab === "phylogeny" && !current?.phylogenyNewick && !current?.isLoading && current?.loadError && (
        <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
      )}
      {activeTab === "phylogeny" && !current?.phylogenyNewick && !current?.isLoading && !current?.loadError && (
        <div className="rounded border p-4 text-sm text-muted-foreground">No phylogenetic tree available.</div>
      )}

      {activeTab === "lineage" && current?.lineagePlot && (
        <TreeView
          source={{ kind: "lineage", lineagePlot: current.lineagePlot, nodeAttributes: current.nodeAttributes }}
          displayIdField={displayIdField || undefined}
          showLabels={showLabels}
          showInternalNodes={showInternalNodes}
          showNodeNumbers={showNodeNumbers}
          colorByField={colorByField}
          colorDomain={colorDomain}
          germlineLabel={germlineLabel}
          unknownValue={unknownValue}
          filename={lineageDownloadName}
          newickText={lineageNewick}
          displayNewick={current.displayNewick}
          collapseSignal={collapseSignal}
          height={viewportHeight}
        />
      )}
      {activeTab === "lineage" && !current?.lineagePlot && current?.isLoading && (
        <TreeSkeleton height={viewportHeight} />
      )}
      {activeTab === "lineage" && !current?.lineagePlot && !current?.isLoading && current?.loadError && (
        <div className="rounded border p-4 text-sm text-red-600">{current.loadError}</div>
      )}
      {activeTab === "lineage" && !current?.lineagePlot && !current?.isLoading && !current?.loadError && (
        <div className="rounded border p-4 text-sm text-muted-foreground">No lineage plot available.</div>
      )}
    </>
  );
}
