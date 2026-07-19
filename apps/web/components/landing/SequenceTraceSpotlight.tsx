import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Button } from "@/components/ui/button";

// A decorative motif for the Sequence Trace spotlight: two independent
// reconstructions of the same clone, with one shared sequence highlighted in
// each and a dotted connector showing it lands in a different place. Pure SVG,
// token-coloured, aria-hidden. Reuses the phylo-* animation classes from
// globals.css, which already respect prefers-reduced-motion.
type Pt = readonly [number, number];

type MiniTree = {
  root: Pt;
  branches: readonly { from: Pt; to: Pt }[];
  tips: readonly Pt[];
  highlight: number; // index into tips of the shared sequence
};

const LEFT: MiniTree = {
  root: [40, 150],
  branches: [
    { from: [40, 150], to: [120, 95] },
    { from: [40, 150], to: [120, 205] },
    { from: [120, 95], to: [205, 60] },
    { from: [120, 95], to: [205, 120] },
    { from: [120, 205], to: [205, 180] },
    { from: [120, 205], to: [205, 240] },
  ],
  tips: [
    [205, 60],
    [205, 120],
    [205, 180],
    [205, 240],
  ],
  highlight: 1,
};

const RIGHT: MiniTree = {
  root: [270, 150],
  branches: [
    { from: [270, 150], to: [350, 95] },
    { from: [270, 150], to: [350, 205] },
    { from: [350, 95], to: [435, 60] },
    { from: [350, 95], to: [435, 120] },
    { from: [350, 205], to: [435, 180] },
    { from: [350, 205], to: [435, 240] },
  ],
  tips: [
    [435, 60],
    [435, 120],
    [435, 180],
    [435, 240],
  ],
  highlight: 3,
};

function MiniTreeGroup({ tree, delayBase }: { tree: MiniTree; delayBase: number }) {
  return (
    <g strokeLinecap="round">
      {tree.branches.map((b, i) => (
        <line
          key={`b-${i}`}
          x1={b.from[0]}
          y1={b.from[1]}
          x2={b.to[0]}
          y2={b.to[1]}
          pathLength={1}
          strokeWidth={2}
          stroke="currentColor"
          className="text-primary/30 phylo-draw"
          style={{ animationDelay: `${delayBase + i * 0.08}s` }}
        />
      ))}
      {/* internal + root nodes */}
      {[tree.root, tree.branches[0].to, tree.branches[1].to].map((p, i) => (
        <circle
          key={`n-${i}`}
          cx={p[0]}
          cy={p[1]}
          r={i === 0 ? 5 : 3.5}
          className="fill-primary/70 phylo-node-in"
          style={{ animationDelay: `${delayBase + 0.2 + i * 0.06}s` }}
        />
      ))}
      {/* tips — the shared sequence is highlighted */}
      {tree.tips.map((p, i) => {
        const isHit = i === tree.highlight;
        return (
          <g key={`t-${i}`}>
            {isHit && <circle cx={p[0]} cy={p[1]} r={11} className="fill-primary/15" />}
            <circle
              cx={p[0]}
              cy={p[1]}
              r={isHit ? 6 : 4.5}
              className={
                isHit
                  ? "fill-primary stroke-primary phylo-node-in"
                  : "fill-muted-foreground/40 phylo-node-in"
              }
              strokeWidth={isHit ? 2 : 0}
              style={{ animationDelay: `${delayBase + 0.5 + i * 0.07}s` }}
            />
          </g>
        );
      })}
    </g>
  );
}

function SequenceTraceArt({ className }: { className?: string }) {
  const leftHit = LEFT.tips[LEFT.highlight];
  const rightHit = RIGHT.tips[RIGHT.highlight];
  return (
    <svg viewBox="0 0 475 300" className={className} fill="none" aria-hidden="true">
      <g className="phylo-float">
        <MiniTreeGroup tree={LEFT} delayBase={0.1} />
        <MiniTreeGroup tree={RIGHT} delayBase={0.4} />

        {/* dotted connector: the same sequence, placed differently */}
        <line
          x1={leftHit[0]}
          y1={leftHit[1]}
          x2={rightHit[0]}
          y2={rightHit[1]}
          stroke="currentColor"
          strokeWidth={1.5}
          strokeDasharray="3 5"
          className="text-primary/50"
        />

        {/* faint method labels */}
        <text x={122} y={285} textAnchor="middle" fontSize={10} className="fill-muted-foreground opacity-50">
          Method A
        </text>
        <text x={352} y={285} textAnchor="middle" fontSize={10} className="fill-muted-foreground opacity-50">
          Method B
        </text>
      </g>
    </svg>
  );
}

export function SequenceTraceSpotlight() {
  return (
    <section className="border-b">
      <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 lg:grid-cols-2">
        <div className="space-y-5">
          <p className="text-xs font-semibold uppercase tracking-wide text-primary">
            Analysis, not just display
          </p>
          <h2 className="text-3xl font-bold tracking-tight">
            Follow one sequence across four methods
          </h2>
          <p className="text-base leading-relaxed text-muted-foreground">
            Run the same clone through Dowser, GCtree, BrepPhylo and ClonalTree and each
            reconstruction places its sequences a little differently — a tip here, a deeper branch
            there. Sequence Trace pins one sequence and shows you exactly where every method puts it,
            side by side, so the disagreement between methods becomes something you can actually read.
          </p>
          <Link href="/dashboard/comparison">
            <Button size="lg" className="gap-2 px-6 text-base">
              Open Sequence Trace
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>

        <div className="relative">
          <SequenceTraceArt className="mx-auto w-full max-w-lg text-primary" />
        </div>
      </div>
    </section>
  );
}
