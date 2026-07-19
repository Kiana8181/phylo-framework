import type { ReactNode } from "react";

/**
 * A generated static diagram shown on a fixed light card. The SVGs are baked at
 * authoring time (scripts/generate-docs-diagrams) and cannot read the site's
 * light/dark theme tokens, so they render on a constant white background. The
 * image is shown at natural size inside a horizontally scrollable card, so dense
 * diagrams scroll rather than shrinking their text past readability.
 */
export function DiagramFigure({
  src,
  alt,
  caption,
}: {
  src: string;
  alt: string;
  caption: ReactNode;
}) {
  return (
    <figure className="space-y-3">
      <div className="overflow-x-auto rounded-lg border bg-white p-4 sm:p-6">
        {/* eslint-disable-next-line @next/next/no-img-element -- static generated SVG in /public */}
        <img src={src} alt={alt} className="mx-auto block h-auto max-w-none" />
      </div>
      <figcaption className="text-sm text-muted-foreground">{caption}</figcaption>
    </figure>
  );
}
