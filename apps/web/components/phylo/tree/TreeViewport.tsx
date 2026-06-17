"use client";

import { API_ROUTES } from "@phylo/contracts";
import TreeSVG from "@/components/TreeSVG";
import LineageSVG from "@/components/LineageSVG";
import ArtifactImage from "@/components/phylo/ArtifactImage";
import { Loading } from "@/components/ui/loading";
import type { TreeVM } from "@/components/phylo/TreesCarousel";

export type TreeViewportProps = {
  activeTab: "method" | "phylogeny" | "lineage";
  current?: TreeVM;
  idx: number;
  phyloAnnotations: Array<{ label: string } & Record<string, unknown>>;
  colorBy?: string;
  unknownValue?: string;
  displayIdField: string;
  showLabels: boolean;
  showInternalNodes: boolean;
  showNodeNumbers: boolean;
  sizeByField: string;
  lineageDownloadName: string;
  lineageNewick: string;
  /** Override the renderers' scrollable viewport height (fullscreen expand). */
  viewportHeight?: number | string;
};

/** Renders the active tree view (method image / phylogeny / lineage), with its
 *  loading / error / empty states. Shared by the inline display and the
 *  fullscreen expand dialog. */
export default function TreeViewport({
  activeTab,
  current,
  idx,
  phyloAnnotations,
  colorBy,
  unknownValue,
  displayIdField,
  showLabels,
  showInternalNodes,
  showNodeNumbers,
  sizeByField,
  lineageDownloadName,
  lineageNewick,
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
          viewportHeight={viewportHeight}
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
          viewportHeight={viewportHeight}
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
    </>
  );
}
