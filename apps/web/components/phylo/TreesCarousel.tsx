"use client";

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import TreeSVG from "@/components/TreeSVG";
import { ChevronLeft, ChevronRight } from "lucide-react";

type TreesCarouselProps = {
  trees: string[];
  figures?: Record<string, string[]> | null;
  annotations?: any;
  cleanNewick: (s: string) => string;
  colorBy?: string;
  unknownValue?: string;
};

function ensureDataUrl(src?: string | null): string {
  if (!src) return "";
  if (src.startsWith("data:")) return src;
  return `data:image/png;base64,${src}`;
}

function prettyLabel(key: string): string {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export default function TreesCarousel({
  trees,
  figures,
  annotations,
  cleanNewick,
  colorBy,
  unknownValue,
}: TreesCarouselProps) {
  const total = trees?.length ?? 0;
  const [idx, setIdx] = useState(0);

  const canPrev = idx > 0;
  const canNext = idx < Math.max(0, total - 1);

  const current = useMemo(() => {
    if (!total) return null;
    return {
      tree: cleanNewick(trees[idx]),
      png: figures?.phylogeny?.[idx],
      anno: annotations?.[idx],
    };
  }, [idx, trees, figures, annotations, total, cleanNewick]);

  const extraFigures = useMemo(
    () =>
      figures
        ? Object.entries(figures).filter(([key]) => key !== "phylogeny")
        : [],
    [figures]
  );

  if (!total) {
    return (
      <Card className="p-4">
        <div className="text-sm text-muted-foreground">No trees returned.</div>
      </Card>
    );
  }

  return (
    <>
      <Card className="p-4 space-y-3">
        <h4 className="font-medium">Images</h4>

        {extraFigures.length === 0 ? (
          <div className="text-sm text-muted-foreground">No extra figures.</div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            {extraFigures.map(([key, arr]) => {
              const raw = arr?.[0];
              const src = ensureDataUrl(raw);
              if (!src) return null;
              return (
                <div key={key} className="space-y-2">
                  <div className="overflow-hidden rounded border bg-white">
                    <img
                      src={src}
                      alt={key}
                      className="w-full h-auto mx-auto"
                    />
                  </div>
                  <div className="text-xs text-center text-muted-foreground">
                    {prettyLabel(key)}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Trees Card*/}
      <Card className="p-4 space-y-3">
        <div className="flex items-center justify-between">
          <h4 className="font-medium">Trees</h4>
          <div className="text-xs text-muted-foreground">
            {idx + 1} / {total}
          </div>
        </div>

        {/* navigation */}
        <div className="flex items-center justify-between gap-3">
          <button
            className="rounded border px-3 py-1.5 text-sm inline-flex items-center gap-1 disabled:opacity-50"
            onClick={() => canPrev && setIdx((v) => Math.max(0, v - 1))}
            disabled={!canPrev}
          >
            <ChevronLeft className="w-4 h-4" /> Prev
          </button>

          <div className="flex-1 overflow-auto">
            <div className="space-y-2">
              {/* exact PNG from backend */}
              {current?.png && (
                <div className="overflow-hidden">
                  <img
                    src={ensureDataUrl(current.png)}
                    className="rounded border bg-white mx-auto w-full max-w-full h-auto"
                    alt={`Tree ${idx + 1}`}
                  />
                </div>
              )}
              {/* interactive SVG */}
              {current?.tree && (
                <div className="overflow-auto">
                  <TreeSVG
                    newick={current.tree}
                    annotations={current.anno}
                    showLabels
                    colorBy={colorBy}
                    unknownValue={unknownValue}
                  />
                </div>
              )}
            </div>
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
    </>
  );
}
