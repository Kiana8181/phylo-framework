// apps/web/components/TreeSVG.tsx
"use client";

import { useMemo, useRef, useState } from "react";
import { parseNewick, NewickNode } from "@/lib/newick";

type Anno = { label: string; c_call?: string };

type Props = {
  newick: string;
  width?: number;
  height?: number;
  filename?: string;
  fontSize?: number;
  strokeWidth?: number;
  showLabels?: boolean; // default false
  annotations?: Anno[];
  colorMap?: Record<string, string>;
};

type LNode = NewickNode & { parent?: LNode; x?: number; y?: number };

const DEFAULT_COLORS: Record<string, string> = {
  Germline: "#222222",
  IGHA2: "#1abc9c",
  IGHG1: "#e67e22",
  IGHG2: "#34495e",
  IGHG3: "#e91e63",
  IGHG4: "#2ecc71",
};

// Belt & suspenders: clean up R's printed vectors like `[1] "..."`
function sanitizeNewick(s: string): string {
  let x = s.trim();
  x = x.replace(/^\[\d+\]\s*"/, "");
  x = x.replace(/"\s*$/, "");
  if (!x.endsWith(";")) x += ";";
  return x;
}

// lightweight text-width estimator (good enough for margin sizing)
function estimateTextWidth(label: string, fontSize: number) {
  // ~0.6em per character is a decent approximation for sans fonts
  return Math.ceil(fontSize * 0.6 * (label?.length ?? 0));
}

export default function TreeSVG({
  newick,
  width = 900,
  height = 520,
  filename = "tree",
  fontSize = 12,
  strokeWidth = 1,
  showLabels: showLabelsProp = false,
  annotations,
  colorMap,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [showLabels, setShowLabels] = useState<boolean>(showLabelsProp);

  // Annotation lookup by leaf label
  const annoByLabel = useMemo(() => {
    const m: Record<string, { c_call?: string }> = {};
    (annotations ?? []).forEach((a) => {
      if (a?.label) m[a.label] = { c_call: a.c_call };
    });
    return m;
  }, [annotations]);

  const colors = { ...DEFAULT_COLORS, ...(colorMap ?? {}) };

  const layout = useMemo(() => {
    const input = sanitizeNewick(newick);
    const root = parseNewick(input) as LNode;

    // We'll compute leaves early to size the label margin if needed
    const tmpLeaves: LNode[] = [];
    (function collectLeaves(n: LNode) {
      if (!n.children || n.children.length === 0) tmpLeaves.push(n);
      else n.children.forEach((c) => collectLeaves(c as LNode));
    })(root);

    // dynamic right margin when labels are visible
    const longestLabelLen =
      tmpLeaves.length === 0
        ? 0
        : Math.max(...tmpLeaves.map((n) => (n.name ?? "").length));
    const labelPad = 10; // space between plot and labels
    const labelArea =
      showLabels && longestLabelLen
        ? Math.max(
            160,
            estimateTextWidth("W".repeat(longestLabelLen), fontSize) + 18
          )
        : 20;

    const margin = { top: 20, right: labelArea, bottom: 20, left: 20 };
    const innerW = Math.max(1, width - margin.left - margin.right);
    const innerH = Math.max(1, height - margin.top - margin.bottom);

    // y positions (equally spaced)
    const yStep = tmpLeaves.length > 1 ? innerH / (tmpLeaves.length - 1) : 0;
    tmpLeaves.forEach((leaf, i) => (leaf.y = margin.top + i * yStep));

    // longest path length for x scaling
    function pathLen(n: LNode): number {
      const len = n.length ?? 0;
      if (!n.children || n.children.length === 0) return len;
      return len + Math.max(...n.children.map((c) => pathLen(c as LNode)));
    }
    const maxDepth = pathLen(root) || 1;
    const scaleX = innerW / maxDepth;

    // assign x/y recursively
    function assignXY(n: LNode, parent?: LNode) {
      n.parent = parent;
      const parentX = parent?.x ?? margin.left;
      n.x = parentX + (n.length ?? 0) * scaleX;

      if (n.children && n.children.length) {
        n.children.forEach((c) => assignXY(c as LNode, n));
        const ys = n.children.map((c) => (c as LNode).y ?? 0);
        n.y = ys.reduce((a, b) => a + b, 0) / ys.length; // internal at avg y
      } else if (typeof n.y !== "number") {
        n.y = margin.top; // single-node tree edge-case
      }
    }
    assignXY(root, undefined);

    // Align leftmost to left margin
    function minX(n: LNode): number {
      let v = n.x ?? 0;
      (n.children ?? []).forEach((c) => {
        const m = minX(c as LNode);
        if (m < v) v = m;
      });
      return v;
    }
    const dx = margin.left - minX(root);
    if (dx !== 0) {
      (function shift(n: LNode) {
        n.x = (n.x ?? 0) + dx;
        n.children?.forEach((c) => shift(c as LNode));
      })(root);
    }

    // Build edges (rectangular)
    const edges: Array<{ x1: number; y1: number; x2: number; y2: number }> = [];
    function walkEdges(n: LNode) {
      if (!n.children || !n.children.length) return;
      const ys = n.children.map((c) => (c as LNode).y ?? 0);
      const yMin = Math.min(...ys);
      const yMax = Math.max(...ys);
      const x = n.x ?? 0;
      edges.push({ x1: x, y1: yMin, x2: x, y2: yMax });
      n.children.forEach((c) => {
        const cc = c as LNode;
        edges.push({ x1: x, y1: cc.y!, x2: cc.x!, y2: cc.y! });
        walkEdges(cc);
      });
    }
    walkEdges(root);

    // leaf nodes list
    const leafNodes: LNode[] = [];
    (function collect(n: LNode) {
      if (!n.children || !n.children.length) leafNodes.push(n);
      else n.children.forEach((c) => collect(c as LNode));
    })(root);

    // label anchor x: right outside plotting area so labels never sit "inside" the plot
    const plotRightX = width - margin.right; // end of branches
    const labelX = plotRightX + labelPad;

    return { root, edges, leafNodes, margin, labelX };
  }, [newick, width, height, fontSize, showLabels]);

  // Downloads
  function downloadSVG() {
    const svg = svgRef.current;
    if (!svg) return;
    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const blob = new Blob([src], { type: "image/svg+xml;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.svg`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function downloadPNG() {
    const svg = svgRef.current;
    if (!svg) return;
    const serializer = new XMLSerializer();
    const src = serializer.serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      const canvas = document.createElement("canvas");
      canvas.width = width;
      canvas.height = height;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, width, height);
      ctx.drawImage(img, 0, 0);
      const png = canvas.toDataURL("image/png");
      const a = document.createElement("a");
      a.href = png;
      a.download = `${filename}.png`;
      a.click();
    };
    img.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(src);
  }

  function downloadNewick() {
    const txt = sanitizeNewick(newick);
    const blob = new Blob([txt], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${filename}.nwk`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="w-full">
      <svg
        ref={svgRef}
        width={width}
        height={height}
        className="rounded border bg-background text-foreground"
        role="img"
      >
        {/* branches */}
        <g
          stroke="currentColor"
          strokeWidth={strokeWidth}
          vectorEffect="non-scaling-stroke"
        >
          {layout.edges.map((e, i) => (
            <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} />
          ))}
        </g>

        {/* tip points (colored by c_call / Germline) */}
        <g>
          {layout.leafNodes.map((n, i) => {
            const label = n.name ?? "";
            const call = annoByLabel[label]?.c_call ?? "Germline";
            const fill = colors[call] ?? "#444";
            return <circle key={i} cx={n.x!} cy={n.y!} r={3} fill={fill} />;
          })}
        </g>

        {/* labels outside + leader lines */}
        {showLabels && (
          <g fontSize={fontSize} fill="currentColor">
            {layout.leafNodes.map((n, i) => (
              <g key={i}>
                <line
                  x1={n.x!}
                  y1={n.y!}
                  x2={Math.round(layout.labelX) - 4}
                  y2={n.y!}
                  stroke="currentColor"
                  strokeWidth={0.5}
                  opacity={0.4}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={Math.round(layout.labelX)}
                  y={n.y!}
                  dominantBaseline="middle" // <-- aligns text vertically to the tip
                >
                  {n.name ?? ""}
                </text>
              </g>
            ))}
          </g>
        )}
      </svg>

      <div className="mt-3 flex flex-wrap gap-2">
        <button
          onClick={downloadPNG}
          className="rounded border px-3 py-1 text-sm"
        >
          Download PNG
        </button>
        <button
          onClick={downloadSVG}
          className="rounded border px-3 py-1 text-sm"
        >
          Download SVG
        </button>
        <button
          onClick={downloadNewick}
          className="rounded border px-3 py-1 text-sm"
        >
          Download Newick
        </button>

        <button
          onClick={() => setShowLabels((v) => !v)}
          className="ml-auto rounded border px-3 py-1 text-sm"
          aria-pressed={showLabels}
          aria-label="Toggle labels"
          title="Toggle tip labels"
        >
          {showLabels ? "Hide labels" : "Show labels"}
        </button>
      </div>
    </div>
  );
}
