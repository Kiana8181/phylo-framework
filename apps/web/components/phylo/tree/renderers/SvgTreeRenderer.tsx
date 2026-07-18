"use client";

import { useState } from "react";
import MatchArrow from "@/components/phylo/tree/MatchArrow";
import { splitByHighlight, LABEL_FONT_SIZE } from "@/components/phylo/tree/core";
import type { TreeRenderProps } from "./TreeRenderer";

const MATCH_FILL = "#dc2626";
const MATCH_STROKE = "#b91c1c";

/**
 * The default (and only) tree renderer. Draws layout-derived `NodeVisual`s and
 * elbow edges as SVG inside the parent's transformed `<g>`. Nodes are keyed by
 * stable id so React never remounts them on pan. No `<title>` tooltips — hover
 * only communicates affordance (cursor + emphasis); details come from the modal
 * on click.
 */
export default function SvgTreeRenderer({
  nodes,
  edges,
  labelX,
  connectorX,
  highlightText,
  markMatches,
  onNodeClick,
  onNodeContextMenu,
}: TreeRenderProps) {
  const [hoveredId, setHoveredId] = useState<string | null>(null);

  return (
    <>
      {/* branches */}
      <g fill="none" stroke="currentColor" strokeWidth={1.2} opacity={0.8} vectorEffect="non-scaling-stroke">
        {edges.map((e) => (
          <path key={e.key} d={e.d} />
        ))}
      </g>

      {/* nodes */}
      <g>
        {nodes.map((n) => {
          const hovered = hoveredId === n.id;
          const fill = n.hollow ? "none" : n.isMatch ? MATCH_FILL : n.fill;
          const stroke = n.hollow
            ? "currentColor"
            : n.isMatch
              ? MATCH_STROKE
              : hovered
                ? "#0f172a"
                : n.stroke ?? "none";
          const strokeWidth = n.hollow ? 1.2 : n.isMatch ? 2.5 : hovered ? 2.6 : n.strokeWidth;
          return (
            <g
              key={n.id}
              onMouseEnter={() => setHoveredId(n.id)}
              onMouseLeave={() => setHoveredId(null)}
              onClick={() => onNodeClick(n.id)}
              onContextMenu={(e) => {
                // Phase 3 wires collapse here; keep the handler now so the seam exists.
                onNodeContextMenu(n.id);
                void e;
              }}
              style={{ cursor: "pointer" }}
            >
              <circle
                cx={n.cx}
                cy={n.cy}
                r={n.r}
                fill={fill}
                stroke={stroke}
                strokeWidth={strokeWidth}
                opacity={n.hollow ? 0.75 : hovered || n.isMatch ? 1 : 0.95}
              />
              {n.numberText && (
                <text x={n.cx + 6} y={n.cy - 6} fontSize={9} fill="currentColor" opacity={0.8}>
                  {n.numberText}
                </text>
              )}
              {markMatches && n.isMatch && <MatchArrow x={n.cx} y={n.cy} gap={n.r + 6} />}
            </g>
          );
        })}
      </g>

      {/* labels */}
      <g fontSize={LABEL_FONT_SIZE} fill="currentColor">
        {nodes
          .filter((n) => n.labelShown && n.labelText)
          .map((n) => (
            <g key={`label-${n.id}`}>
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
                fill={n.isMatch ? MATCH_FILL : "currentColor"}
                fontWeight={n.isMatch ? "bold" : undefined}
              >
                {splitByHighlight(n.labelText, highlightText ?? "").map((seg, i) =>
                  seg.highlight ? (
                    <tspan key={i} fill={MATCH_FILL} fontWeight="bold">
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
    </>
  );
}
