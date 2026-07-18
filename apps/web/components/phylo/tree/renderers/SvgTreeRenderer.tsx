"use client";

import { useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import MatchArrow from "@/components/phylo/tree/MatchArrow";
import { splitByHighlight, LABEL_FONT_SIZE, LOD_LABELS_K } from "@/components/phylo/tree/core";
import type { TreeRenderProps } from "./TreeRenderer";

const RING_COLOR = "var(--tree-match)"; // legend-highlight + search-match ring
const PATH_COLOR = "var(--tree-trace)"; // root→match path emphasis
const FADE_OPACITY = 0.15; // Sequence-Trace context (out-of-focus)
const DOT_SCREEN_R = 1.5; // fixed screen-radius (px) for the zoomed-out "dots" LOD
const LONG_PRESS_MS = 500;
const LONG_PRESS_MOVE = 8; // px of movement that cancels a long-press

/**
 * The default (and only) tree renderer. Draws layout-derived `NodeVisual`s,
 * collapsed-subtree `GlyphVisual` wedges, and elbow edges as SVG inside the
 * parent's transformed `<g>`. No `<title>` tooltips — hover shows affordance;
 * details come from the modal on click. Semantic zoom (LOD) is driven by
 * `transform.k`; text/chevrons stay screen-constant via `1/k` counter-scaling.
 */
export default function SvgTreeRenderer({
  nodes,
  edges,
  glyphs,
  transform,
  lod,
  labelX,
  connectorX,
  highlightText,
  markMatches,
  onNodeClick,
  onToggleCollapse,
}: TreeRenderProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);
  const k = transform.k || 1;
  const dots = lod === "dots";
  const showText = !dots; // labels, connectors, glyph labels (hybrid-scaled)
  const showArrows = !dots;
  const showChevrons = !dots && k >= LOD_LABELS_K; // avoid chevron clutter at low zoom
  // Hybrid label scale: shrink with zoom-out (so labels fit at fit in small panes,
  // like before LOD), but hold at a constant screen size once zoomed in past 1:1
  // (so text never becomes a blob). Both node numbers and glyph labels follow it.
  const textK = Math.max(k, 1);
  const fontSize = LABEL_FONT_SIZE / textK;

  // Long-press (touch) → toggle collapse, without stealing pan from d3-zoom.
  const pressRef = useRef<{ id: string; x: number; y: number; timer: number } | null>(null);
  const cancelPress = () => {
    if (pressRef.current) {
      window.clearTimeout(pressRef.current.timer);
      pressRef.current = null;
    }
  };
  const onPointerDown = (id: string) => (e: PointerEvent) => {
    if (e.pointerType !== "touch") return;
    cancelPress();
    const timer = window.setTimeout(() => {
      onToggleCollapse(id);
      pressRef.current = null;
    }, LONG_PRESS_MS);
    pressRef.current = { id, x: e.clientX, y: e.clientY, timer };
  };
  const onPointerMove = (e: PointerEvent) => {
    const p = pressRef.current;
    if (!p) return;
    if (Math.abs(e.clientX - p.x) > LONG_PRESS_MOVE || Math.abs(e.clientY - p.y) > LONG_PRESS_MOVE) {
      cancelPress();
    }
  };

  const nodeKeyDown = (id: string, collapsible: boolean) => (e: KeyboardEvent) => {
    if (e.key === "Enter") {
      e.preventDefault();
      onNodeClick(id);
    } else if (e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      if (collapsible) onToggleCollapse(id);
    }
  };
  const glyphKeyDown = (id: string) => (e: KeyboardEvent) => {
    if (e.key === "Enter" || e.key === " " || e.key === "Spacebar") {
      e.preventDefault();
      onToggleCollapse(id);
    }
  };

  return (
    <>
      {/* branches (path edges emphasised, out-of-focus edges dimmed) */}
      <g fill="none">
        {edges.map((e) => (
          <path
            key={e.key}
            d={e.d}
            stroke={e.onPath ? PATH_COLOR : "currentColor"}
            strokeWidth={e.onPath ? 2.4 : 1.2}
            opacity={e.faded ? FADE_OPACITY : e.onPath ? 1 : 0.8}
            vectorEffect="non-scaling-stroke"
          />
        ))}
      </g>

      {/* collapsed-subtree wedges (left-click / Enter / Space → expand) */}
      <g>
        {glyphs.map((g) => (
          <g
            key={g.id}
            role="button"
            aria-expanded={false}
            aria-label={`Collapsed subtree${g.labelText ? ` ${g.labelText}` : ""}`}
            tabIndex={g.faded ? -1 : 0}
            style={{
              cursor: g.faded ? "default" : "pointer",
              outline: "none",
              opacity: g.faded ? FADE_OPACITY : 1,
              pointerEvents: g.faded ? "none" : undefined,
            }}
            onClick={() => onToggleCollapse(g.id)}
            onKeyDown={glyphKeyDown(g.id)}
          >
            <path
              d={`M ${g.apexX} ${g.y} L ${g.farX} ${g.y - g.halfHeight} L ${g.farX} ${g.y + g.halfHeight} Z`}
              fill={g.fill}
              fillOpacity={g.striped ? 0.5 : 0.9}
              stroke="currentColor"
              strokeWidth={0.75}
              vectorEffect="non-scaling-stroke"
            />
            {showText && g.labelText && (
              <text x={g.farX + 6} y={g.y} dominantBaseline="middle" fontSize={fontSize} fill="currentColor">
                {g.labelText}
              </text>
            )}
          </g>
        ))}
      </g>

      {/* nodes */}
      <g>
        {nodes.map((n) => {
          const hovered = hoveredId === n.id;
          const r = dots ? DOT_SCREEN_R / k : n.r;
          // Matches keep their field colour and get a ring (Phase 5), unified with
          // the Phase-4 legend-highlight ring.
          const ringed = n.ringed || n.isMatch;
          const fill = n.hollow ? "none" : n.fill;
          const stroke = n.hollow ? "currentColor" : hovered ? "#0f172a" : n.stroke ?? "none";
          const strokeWidth = n.hollow ? 1.2 : hovered ? 2.6 : n.strokeWidth;
          return (
            <g
              key={n.id}
              role="button"
              aria-expanded={n.isCollapsible ? true : undefined}
              tabIndex={n.faded ? -1 : 0}
              style={{
                cursor: n.faded ? "default" : "pointer",
                outline: "none",
                opacity: n.faded ? FADE_OPACITY : 1,
                pointerEvents: n.faded ? "none" : undefined,
              }}
              onMouseEnter={() => setHoveredId(n.id)}
              onMouseLeave={() => setHoveredId(null)}
              onClick={() => onNodeClick(n.id)}
              onContextMenu={(e) => {
                e.preventDefault();
                onToggleCollapse(n.id);
              }}
              onKeyDown={nodeKeyDown(n.id, n.isCollapsible)}
              onPointerDown={onPointerDown(n.id)}
              onPointerMove={onPointerMove}
              onPointerUp={cancelPress}
              onPointerLeave={cancelPress}
            >
              <circle
                cx={n.cx}
                cy={n.cy}
                r={r}
                fill={fill}
                stroke={stroke}
                strokeWidth={strokeWidth}
                opacity={n.hollow ? 0.75 : hovered ? 1 : 0.95}
              />
              {ringed && (
                <circle
                  cx={n.cx}
                  cy={n.cy}
                  r={r + 3}
                  fill="none"
                  stroke={RING_COLOR}
                  strokeWidth={3}
                  vectorEffect="non-scaling-stroke"
                />
              )}
              {n.numberText && showText && (
                <text x={n.cx + 6} y={n.cy - 6} fontSize={9 / textK} fill="currentColor" opacity={0.8}>
                  {n.numberText}
                </text>
              )}
              {/* collapse chevron on expanded collapsible nodes (screen-constant) */}
              {showChevrons && n.isCollapsible && (
                <g
                  transform={`translate(${n.cx} ${n.cy}) scale(${1 / k})`}
                  onClick={(e) => {
                    e.stopPropagation();
                    onToggleCollapse(n.id);
                  }}
                  aria-hidden="true"
                >
                  <path
                    d={`M ${n.r * k + 3} -4 L ${n.r * k + 8} 0 L ${n.r * k + 3} 4 Z`}
                    fill="currentColor"
                    opacity={0.55}
                  />
                </g>
              )}
              {showArrows && markMatches && n.isMatch && <MatchArrow x={n.cx} y={n.cy} gap={r + 6} />}
            </g>
          );
        })}
      </g>

      {/* labels */}
      {showText && (
        <g fill="currentColor">
          {nodes
            .filter((n) => n.labelShown && n.labelText)
            .map((n) => (
              <g key={`label-${n.id}`} opacity={n.faded ? FADE_OPACITY : 1}>
                <line
                  x1={n.cx}
                  y1={n.cy}
                  x2={connectorX}
                  y2={n.cy}
                  stroke="currentColor"
                  strokeWidth={0.5}
                  opacity={0.4}
                  vectorEffect="non-scaling-stroke"
                />
                <text
                  x={labelX}
                  y={n.cy}
                  dominantBaseline="middle"
                  fontSize={fontSize}
                  fill={n.isMatch ? RING_COLOR : "currentColor"}
                  fontWeight={n.isMatch ? "bold" : undefined}
                >
                  {splitByHighlight(n.labelText, highlightText ?? "").map((seg, i) =>
                    seg.highlight ? (
                      <tspan key={i} fill={RING_COLOR} fontWeight="bold">
                        {seg.text}
                      </tspan>
                    ) : (
                      <tspan key={i}>{seg.text}</tspan>
                    ),
                  )}
                </text>
              </g>
            ))}
        </g>
      )}
    </>
  );
}
