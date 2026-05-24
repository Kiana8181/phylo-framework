"use client";

import { useMemo, useRef } from "react";
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
  displayIdField?: string | null;
  /** When set, tip nodes whose label/tooltip contains this text get highlighted. */
  highlightText?: string | null;
  showInternalNodes?: boolean;
  showNodeNumbers?: boolean;
  /** Numeric annotation field used to scale tip circle radius. */
  sizeBy?: string | null;
};

type LNode = NewickNode & { parent?: LNode; x?: number; y?: number };

const TREE_VIEWPORT_HEIGHT = 520;

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
  field: string | null,
  unknownValue: string,
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
  colorField: string | null,
  displayField: string | null,
): string {
  if (typeof anno?.tooltip === "string" && anno.tooltip.trim()) {
    return anno.tooltip.trim();
  }

  const lines: string[] = [];

  // 1) display label / selected identity field
  const displayValue = (displayField && String((anno as any)?.[displayField] ?? "").trim()) || label;
  if (displayValue) lines.push(displayValue);

  if (!anno) return lines.join("\n");

  // 2) sequence_id (if present and not duplicate of label)
  const seqId = String(anno.sequence_id ?? "").trim();
  if (seqId && seqId !== displayValue) lines.push(`sequence_id: ${seqId}`);

  // 3) colorBy field (if set)
  if (colorField) {
    const cval = String(anno[colorField] ?? "").trim();
    if (cval) lines.push(`${colorField}: ${cval}`);
  }

  // 4) all remaining fields (sorted), excluding label + sequence_id + colorField
  const skip = new Set<string>(["label", "sequence_id", "tooltip"]);
  if (displayField) skip.add(displayField);
  if (colorField) skip.add(colorField);

  const extras = Object.keys(anno)
    .filter((k) => !skip.has(k))
    .sort((a, b) => a.localeCompare(b, "en"));

  for (const k of extras) {
    const v = String(anno[k] ?? "").trim();
    if (v) lines.push(`${k}: ${v}`);
  }

  return lines.join("\n");
}

function splitByHighlight(
  text: string,
  highlight: string
): Array<{ text: string; highlight: boolean }> {
  if (!highlight?.trim()) return [{ text, highlight: false }];
  const needle = highlight.trim();
  const lower = text.toLowerCase();
  const needleLower = needle.toLowerCase();
  const parts: Array<{ text: string; highlight: boolean }> = [];
  let start = 0;
  while (true) {
    const i = lower.indexOf(needleLower, start);
    if (i === -1) {
      if (start < text.length) parts.push({ text: text.slice(start), highlight: false });
      break;
    }
    if (i > start) parts.push({ text: text.slice(start, i), highlight: false });
    parts.push({ text: text.slice(i, i + needle.length), highlight: true });
    start = i + needle.length;
  }
  return parts.length ? parts : [{ text, highlight: false }];
}

function isBlackColor(value: string): boolean {
  const c = value.trim().toLowerCase();
  if (!c) return false;
  if (c === "black" || c === "#000" || c === "#000000" || c === "#000000ff") return true;

  const rgb = c.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const parts = rgb[1].split(",").map((v) => Number(v.trim()));
    if (parts.length >= 3) {
      const [r, g, b] = parts;
      return r === 0 && g === 0 && b === 0;
    }
  }

  return false;
}

function buildAnnoLookup(annotations?: Anno[]): Record<string, Anno> {
  const m: Record<string, Anno> = {};
  (annotations ?? []).forEach((a) => {
    if (!a) return;
    const keys = [a.final_tip_label, a.sequence_id, a.label].filter(
      (k): k is string => typeof k === "string" && k.trim().length > 0,
    );
    for (const key of keys) {
      m[key.trim()] = a;
    }
  });
  return m;
}

function resolveAnno(lookup: Record<string, Anno>, tipName: string): Anno | undefined {
  return lookup[tipName];
}

function buildTipSizeScale(
  annotations: Anno[] | undefined,
  field: string | null | undefined,
  minRadius = 2.5,
  maxRadius = 10,
) {
  if (!field || !annotations?.length) return null;
  const vals = annotations
    .map((row) => Number(row[field]))
    .filter((v) => Number.isFinite(v) && v > 0);
  if (!vals.length) return null;
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  return (anno: Anno | undefined) => {
    const v = Number(anno?.[field]);
    if (!Number.isFinite(v) || v <= 0) return minRadius;
    if (min === max) return (minRadius + maxRadius) / 2;
    return minRadius + ((v - min) / (max - min)) * (maxRadius - minRadius);
  };
}

export default function TreeSVG({
  newick,
  width = 900,
  height = 520,
  filename = "tree",
  fontSize = 12,
  strokeWidth = 1,
  showLabels = false,
  annotations,
  colorMap,
  colorBy,
  unknownValue,
  displayIdField,
  highlightText,
  showInternalNodes = false,
  showNodeNumbers = false,
  sizeBy = null,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);

  const coloringEnabled = !!colorBy;
  const colorField = colorBy || null;
  const unknown = (unknownValue && unknownValue.trim()) || "unknown";

  const annoByLabel = useMemo(() => buildAnnoLookup(annotations), [annotations]);
  const tipSizeScale = useMemo(
    () => buildTipSizeScale(annotations, sizeBy),
    [annotations, sizeBy],
  );

  const colors = useMemo(() => {
    if (!coloringEnabled) return {};
    if (colorMap && Object.keys(colorMap).length) {
      return {
        ...colorMap,
        Germline: "#000000",
        [unknown]: "#000000",
      };
    }
    return buildColorMapDistinct(annotations, colorField, unknown);
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
      tmpLeaves.length === 0 ? 0 : Math.max(...tmpLeaves.map((n) => (n.name ?? "").length));
    const labelPad = 10;
    const labelArea =
      showLabels && longestLabelLen
        ? Math.max(160, estimateTextWidth("W".repeat(longestLabelLen), fontSize) + 18)
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
    const internalNodes: LNode[] = [];
    (function collect(n: LNode) {
      if (!n.children || !n.children.length) leafNodes.push(n);
      else {
        internalNodes.push(n);
        n.children.forEach((c) => collect(c as LNode));
      }
    })(root);

    const plotRightX = width - margin.right;
    const labelX = plotRightX + labelPad;

    return { root, edges, leafNodes, internalNodes, margin, labelX };
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
    <div className="space-y-3">
      <div
        className="w-full overflow-auto rounded border"
        style={{ height: TREE_VIEWPORT_HEIGHT, maxHeight: TREE_VIEWPORT_HEIGHT }}
      >
        <svg
          ref={svgRef}
          width={width}
          height={computedHeight}
          data-tree-zoom-target="true"
          className="block bg-background text-foreground"
          role="img"
        >
        {/* branches */}
        <g stroke="currentColor" strokeWidth={strokeWidth} vectorEffect="non-scaling-stroke">
          {layout.edges.map((e, i) => (
            <line key={i} x1={e.x1} y1={e.y1} x2={e.x2} y2={e.y2} />
          ))}
        </g>

        {/* tips */}
        <g>
          {layout.leafNodes.map((n, i) => {
            const label = n.name ?? "";
            const anno = resolveAnno(annoByLabel, label);
            const defaultLeafFill = "var(--foreground)";

            let fill = defaultLeafFill;
            if (coloringEnabled && colorField) {
              const call = (anno?.[colorField] as string) || "";
              if (call && call !== "Germline" && call !== unknown) {
                const resolved = colors[call] ?? defaultLeafFill;
                fill = isBlackColor(resolved) ? defaultLeafFill : resolved;
              }
            }

            const title = buildTipTitle(label, anno, colorField, displayIdField || null);
            const displayLabel =
              (displayIdField && String(anno?.[displayIdField] ?? "").trim()) || label;
            const needle = highlightText?.trim();
            const matchesHighlight = Boolean(
              needle &&
                (title.toLowerCase().includes(needle.toLowerCase()) ||
                  label.toLowerCase().includes(needle.toLowerCase()) ||
                  displayLabel.toLowerCase().includes(needle.toLowerCase()))
            );
            const tipFill = matchesHighlight ? "#dc2626" : fill;
            const tipStroke = matchesHighlight ? "#b91c1c" : undefined;
            const tipStrokeWidth = matchesHighlight ? 2 : 0;
            const tipRadius = tipSizeScale ? tipSizeScale(anno) : 3;

            return (
              <circle
                key={i}
                cx={n.x!}
                cy={n.y!}
                r={tipRadius}
                fill={tipFill}
                stroke={tipStroke}
                strokeWidth={tipStrokeWidth}
                style={{ cursor: "pointer" }}
              >
                <title>{title}</title>
              </circle>
            );
          })}
        </g>

        {showInternalNodes &&
          layout.internalNodes.map((n, i) => (
            <g key={`internal-${i}`}>
              <circle
                cx={n.x!}
                cy={n.y!}
                r={2.5}
                fill="none"
                stroke="currentColor"
                strokeWidth={1.2}
                opacity={0.75}
              />
              {(showNodeNumbers || showInternalNodes) && (
                <text
                  x={(n.x ?? 0) + 6}
                  y={(n.y ?? 0) - 6}
                  fontSize={9}
                  fill="currentColor"
                  opacity={0.8}
                >
                  {showNodeNumbers ? `#${i + 1}` : ""}
                </text>
              )}
            </g>
          ))}

        {/* labels */}
        {showLabels && (
          <g fontSize={fontSize} fill="currentColor">
            {layout.leafNodes.map((n, i) => {
              const label = n.name ?? "";
              const anno = resolveAnno(annoByLabel, label);
              const title = buildTipTitle(label, anno, colorField, displayIdField || null);
              const displayLabel = (displayIdField && String(anno?.[displayIdField] ?? "").trim()) || label;
              const labelParts = splitByHighlight(displayLabel, highlightText ?? "");
              return (
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
                  <text x={Math.round(layout.labelX)} y={n.y!} dominantBaseline="middle">
                    {labelParts.map((seg, j) =>
                      seg.highlight ? (
                        <tspan key={j} fill="#dc2626" fontWeight="bold">
                          {seg.text}
                        </tspan>
                      ) : (
                        <tspan key={j}>{seg.text}</tspan>
                      )
                    )}
                    <title>{title}</title>
                  </text>
                </g>
              );
            })}
          </g>
        )}
        </svg>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={downloadPNG} className="rounded border px-3 py-1 text-sm">
          Download PNG
        </button>
        <button onClick={downloadSVG} className="rounded border px-3 py-1 text-sm">
          Download SVG
        </button>
        <button onClick={downloadNewick} className="rounded border px-3 py-1 text-sm">
          Download Newick
        </button>
      </div>
    </div>
  );
}
