// A decorative, token-coloured phylogenetic-tree motif for the landing hero.
// Pure SVG; animation is driven by CSS classes in globals.css and is disabled
// under prefers-reduced-motion. Marked aria-hidden — it is purely decorative.

type Pt = readonly [number, number];

const ROOT: Pt = [60, 180];
const L1: Pt[] = [
  [170, 110],
  [170, 250],
];
const L2: Pt[] = [
  [300, 70],
  [300, 150],
  [300, 210],
  [300, 300],
];
const TIPS: Pt[] = [
  [424, 50],
  [424, 95],
  [424, 130],
  [424, 175],
  [424, 205],
  [424, 245],
  [424, 285],
  [424, 325],
];

type Branch = { from: Pt; to: Pt; delay: number };

const BRANCHES: Branch[] = [
  // root → level 1
  { from: ROOT, to: L1[0], delay: 0.1 },
  { from: ROOT, to: L1[1], delay: 0.1 },
  // level 1 → level 2
  { from: L1[0], to: L2[0], delay: 0.45 },
  { from: L1[0], to: L2[1], delay: 0.45 },
  { from: L1[1], to: L2[2], delay: 0.45 },
  { from: L1[1], to: L2[3], delay: 0.45 },
  // level 2 → tips
  { from: L2[0], to: TIPS[0], delay: 0.8 },
  { from: L2[0], to: TIPS[1], delay: 0.8 },
  { from: L2[1], to: TIPS[2], delay: 0.8 },
  { from: L2[1], to: TIPS[3], delay: 0.8 },
  { from: L2[2], to: TIPS[4], delay: 0.8 },
  { from: L2[2], to: TIPS[5], delay: 0.8 },
  { from: L2[3], to: TIPS[6], delay: 0.8 },
  { from: L2[3], to: TIPS[7], delay: 0.8 },
];

const TIP_COLORS = [
  "text-chart-1",
  "text-chart-2",
  "text-chart-3",
  "text-chart-4",
  "text-chart-5",
  "text-chart-1",
  "text-chart-2",
  "text-chart-3",
];

export function PhyloHeroArt({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 480 360"
      className={className}
      fill="none"
      aria-hidden="true"
    >
      {/* soft glow behind the root */}
      <circle cx={60} cy={180} r={120} className="fill-primary/10 phylo-glow" />

      <g className="phylo-float">
        {/* branches */}
        <g strokeLinecap="round">
          {BRANCHES.map((b, i) => (
            <line
              key={i}
              x1={b.from[0]}
              y1={b.from[1]}
              x2={b.to[0]}
              y2={b.to[1]}
              pathLength={1}
              strokeWidth={2.5}
              stroke="currentColor"
              className="text-primary/40 phylo-draw"
              style={{ animationDelay: `${b.delay}s` }}
            />
          ))}
        </g>

        {/* internal nodes */}
        {[ROOT, ...L1, ...L2].map((p, i) => (
          <circle
            key={`n-${i}`}
            cx={p[0]}
            cy={p[1]}
            r={i === 0 ? 7 : 4.5}
            className="fill-primary phylo-node-in"
            style={{ animationDelay: `${0.3 + i * 0.06}s` }}
          />
        ))}

        {/* tips */}
        {TIPS.map((p, i) => (
          <g key={`t-${i}`} className={TIP_COLORS[i]}>
            <circle
              cx={p[0]}
              cy={p[1]}
              r={6.5}
              className="fill-current phylo-node-in"
              style={{ animationDelay: `${1.1 + i * 0.07}s` }}
            />
            <circle cx={p[0]} cy={p[1]} r={11} className="fill-current opacity-15" />
          </g>
        ))}

        {/* germline label near the root */}
        <text
          x={ROOT[0]}
          y={ROOT[1] + 24}
          textAnchor="middle"
          fontSize={10}
          className="fill-muted-foreground opacity-60"
        >
          Germline
        </text>

        {/* faint mutation-distance axis hint beneath the branches */}
        <text
          x={(ROOT[0] + TIPS[0][0]) / 2}
          y={352}
          textAnchor="middle"
          fontSize={10}
          className="fill-muted-foreground opacity-40"
        >
          mutation distance →
        </text>
      </g>
    </svg>
  );
}
