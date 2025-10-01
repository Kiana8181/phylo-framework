"use client";

import { useMemo, useState } from "react";
import { Card } from "@/components/ui/card";
import TreeSVG from "@/components/TreeSVG";
import { ChevronLeft, ChevronRight } from "lucide-react";

type TreesCarouselProps = {
  trees: string[];
  figures?: any;
  annotations?: any;
  cleanNewick: (s: string) => string;
  colorBy?: string;
  unknownValue?: string;
};

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
      png: figures?.png_base64?.[idx],
      anno: annotations?.[idx],
    };
  }, [idx, trees, figures, annotations, total, cleanNewick]);

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

      {/* navigation */}
      <div className="flex items-center justify-between gap-3">
        <button
          className="rounded border px-3 py-1.5 text-sm inline-flex items-center gap-1 disabled:opacity-50"
          onClick={() => canPrev && setIdx((v) => Math.max(0, v - 1))}
          disabled={!canPrev}
        >
          <ChevronLeft className="w-4 h-4" /> Prev
        </button>

        <div className="flex-1">
          <div className="space-y-2">
            {/* exact PNG from backend */}
            {current?.png && (
              <div className="overflow-auto">
                <img
                  src={`data:image/png;base64,${current.png}`}
                  className="rounded border bg-white mx-auto max-w-none"
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
  );
}
