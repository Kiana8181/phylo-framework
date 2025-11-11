"use client";

import { useMemo, useRef, useState } from "react";
import { parseNewick, NewickNode } from "@/lib/newick";

type Anno = { label: string } & Record<string, any>;

type Props = {
  newick: string;
  width?: number;
  height?: number;
  filename?: string;
  fontSize?: number;
  strokeWidth?: number;
  showLabels?: boolean;
  annotations?: Anno[];
  colorMap?: Record<string, string>;
  colorBy?: string | null;
  unknownValue?: string;
};

type LNode = NewickNode & { parent?: LNode; x?: number; y?: number };

/** ---- Helpers ---- */

function sanitizeNewick(s: string): string {
  let x = s.trim();
  x = x.replace(/^\[\d+\]\s*"/, "");
  x = x.replace(/"\s*$/, "");
  if (!x.endsWith(";")) x += ";";
  return x;
}

function estimateTextWidth(label: string, fontSize: number) {
  return Math.ceil(fontSize * 0.6 * (label?.length ?? 0));
}

const GOLDEN_ANGLE = 137.50776405003785;

const SAT_BANDS = [74, 62, 82, 55] as const;
const LIG_BANDS = [45, 58, 36, 66] as const;

function colorByIndex(k: number): string {
  const hue = (k * GOLDEN_ANGLE) % 360;
  const sat = SAT_BANDS[k % SAT_BANDS.length];
  const lig = LIG_BANDS[Math.floor(k / SAT_BANDS.length) % LIG_BANDS.length];

  return `hsl(${hue.toFixed(3)}, ${sat}%, ${lig}%)`;
}

function buildColorMapDistinct(
  list: Anno[] | undefined,
  field: string,
  unknownValue: string
): Record<string, string> {
  const map: Record<string, string> = {};
  if (!list?.length || !field) return map;

  const set = new Set<string>();
  for (const a of list) {
    const v = (a as any)?.[field];
    if (typeof v === "string") {
      const vv = v.trim();
      if (vv && vv !== "Germline" && vv !== unknownValue) {
        set.add(vv);
      }
    }
  }
  const values = Array.from(set).sort((a, b) => a.localeCompare(b, "en"));

  values.forEach((v, i) => {
    map[v] = colorByIndex(i);
  });

  map["Germline"] = "#000000";
  map[unknownValue] = "#000000";
  return map;
}

function buildTipTitle(
  label: string,
  anno: Anno | undefined,
  colorField: string | null
): string {
  const parts: string[] = [];
  parts.push(label || "");

  if (anno && colorField) {
    const v = String(anno[colorField] ?? "").trim();
    if (v) parts.push(`${colorField}: ${v}`);
  }

  if (anno) {
    const extraKeys = Object.keys(anno).filter(
      (k) => k !== "label" && (colorField ? k !== colorField : true)
    );
    if (extraKeys.length > 0) {
      const k = extraKeys[0];
      const vv = String(anno[k] ?? "").trim();
      if (vv) parts.push(`${k}: ${vv}`);
    }
  }

  return parts.filter(Boolean).join("\n");
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
  colorBy,
  unknownValue,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [showLabels, setShowLabels] = useState<boolean>(showLabelsProp);

  const coloringEnabled = !!colorBy;
  const colorField = colorBy || null;
  const unknown = (unknownValue && unknownValue.trim()) || "unknown";

  const annoByLabel = useMemo(() => {
    const m: Record<string, Anno> = {};
    (annotations ?? []).forEach((a) => {
      if (a?.label) m[a.label] = a;
    });
    return m;
  }, [annotations]);

  const colors = useMemo(() => {
    if (!coloringEnabled) return {};
    if (colorMap && Object.keys(colorMap).length) {
      return {
        ...colorMap,
        Germline: "#000000",
        [unknown]: "#000000",
      };
    }
    return buildColorMapDistinct(annotations, colorField!, unknown);
  }, [coloringEnabled, colorMap, annotations, colorField, unknown]);

  const leafCount = useMemo(() => {
    try {
      const root = parseNewick(sanitizeNewick(newick)) as LNode;
      let cnt = 0;
      (function walk(n: LNode) {
        if (!n.children || n.children.length === 0) cnt += 1;
        else n.children.forEach((c) => walk(c as LNode));
      })(root);
      return cnt;
    } catch {
      return 0;
    }
  }, [newick]);

  const tipGap = 14;
  const minBody = Math.max(0, (leafCount - 1) * tipGap);
  const computedHeight = Math.max(height, 20 + minBody + 20);

  const layout = useMemo(() => {
    const input = sanitizeNewick(newick);
    const root = parseNewick(input) as LNode;

    const tmpLeaves: LNode[] = [];
    (function collectLeaves(n: LNode) {
      if (!n.children || n.children.length === 0) tmpLeaves.push(n);
      else n.children.forEach((c) => collectLeaves(c as LNode));
    })(root);

    const longestLabelLen =
      tmpLeaves.length === 0
        ? 0
        : Math.max(...tmpLeaves.map((n) => (n.name ?? "").length));
    const labelPad = 10;
    const labelArea =
      showLabels && longestLabelLen
        ? Math.max(
            160,
            estimateTextWidth("W".repeat(longestLabelLen), fontSize) + 18
          )
        : 20;

    const margin = { top: 20, right: labelArea, bottom: 20, left: 20 };
    const innerW = Math.max(1, width - margin.left - margin.right);
    const innerH = Math.max(1, computedHeight - margin.top - margin.bottom);

    const yStep = tmpLeaves.length > 1 ? innerH / (tmpLeaves.length - 1) : 0;
    tmpLeaves.forEach((leaf, i) => (leaf.y = margin.top + i * yStep));

    function pathLen(n: LNode): number {
      const len = n.length ?? 0;
      if (!n.children || n.children.length === 0) return len;
      return len + Math.max(...n.children.map((c) => pathLen(c as LNode)));
    }
    const maxDepth = pathLen(root) || 1;
    const scaleX = innerW / maxDepth;

    function assignXY(n: LNode, parent?: LNode) {
      n.parent = parent;
      const parentX = parent?.x ?? margin.left;
      n.x = parentX + (n.length ?? 0) * scaleX;

      if (n.children && n.children.length) {
        n.children.forEach((c) => assignXY(c as LNode, n));
        const ys = n.children.map((c) => (c as LNode).y ?? 0);
        n.y = ys.reduce((a, b) => a + b, 0) / ys.length;
      } else if (typeof n.y !== "number") {
        n.y = margin.top;
      }
    }
    assignXY(root, undefined);

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

    const leafNodes: LNode[] = [];
    (function collect(n: LNode) {
      if (!n.children || !n.children.length) leafNodes.push(n);
      else n.children.forEach((c) => collect(c as LNode));
    })(root);

    const plotRightX = width - margin.right;
    const labelX = plotRightX + labelPad;

    return { root, edges, leafNodes, margin, labelX };
  }, [newick, width, computedHeight, fontSize, showLabels]);

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
      canvas.height = computedHeight;
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.fillStyle = "white";
      ctx.fillRect(0, 0, width, computedHeight);
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
    <div className="w-full overflow-auto">
      <svg
        ref={svgRef}
        width={width}
        height={computedHeight}
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

        {/* tips */}
        <g>
          {layout.leafNodes.map((n, i) => {
            const label = n.name ?? "";
            const anno = annoByLabel[label];

            let fill = "#000000";
            if (coloringEnabled && colorField) {
              const call = (anno?.[colorField] as string) || "";
              if (call && call !== "Germline" && call !== unknown) {
                fill = colors[call] ?? "#000000";
              }
            }

            const title = buildTipTitle(label, anno, colorField);

            return (
              <circle
                key={i}
                cx={n.x!}
                cy={n.y!}
                r={3}
                fill={fill}
                style={{ cursor: "pointer" }}
              >
                <title>{title}</title>
              </circle>
            );
          })}
        </g>

        {/* labels */}
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
                  dominantBaseline="middle"
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
