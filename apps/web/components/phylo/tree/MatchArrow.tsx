const ARROW_RED = "#dc2626";

/**
 * A downward arrow drawn just above a tree node to make a searched match easy to
 * spot ("Show me"). Coordinates are in the SVG's user units (same space as the
 * node circles). A gentle SMIL bounce draws the eye; it's disabled under
 * reduced-motion via the `.phylo-marching`-style guard in globals.css.
 */
export default function MatchArrow({
  x,
  y,
  gap = 14,
}: {
  x: number;
  y: number;
  /** Clearance between the node center and the arrow tip. */
  gap?: number;
}) {
  // Arrow tip sits `gap` above the node; the body extends further up.
  const tipY = y - gap;
  return (
    <g transform={`translate(${x}, ${tipY})`} pointerEvents="none" aria-hidden="true">
      <g className="phylo-bounce">
        {/* arrowhead (points down at the node) + short stem */}
        <path
          d="M 0,0 L -6,-8 L -2.5,-8 L -2.5,-18 L 2.5,-18 L 2.5,-8 L 6,-8 Z"
          fill={ARROW_RED}
          stroke="#ffffff"
          strokeWidth={1}
          strokeLinejoin="round"
        />
      </g>
    </g>
  );
}
