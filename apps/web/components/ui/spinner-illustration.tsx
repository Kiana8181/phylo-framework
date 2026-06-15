import type { HTMLAttributes } from "react";
import { cn } from "@/lib/utils";
import loadingSvg from "@/assets/loading.svg";
import loadingDnaSvg from "@/assets/loading-dna.svg";

export type SpinnerIllustrationAsset = "default" | "dna";

const ILLUSTRATION_SRC: Record<SpinnerIllustrationAsset, string> = {
  default: loadingSvg.src,
  dna: loadingDnaSvg.src,
};

/**
 * Animated loading illustration sourced from `assets/loading.svg` or
 * `assets/loading-dna.svg`.
 */
export function SpinnerIllustration({
  asset = "default",
  className,
  ...props
}: HTMLAttributes<HTMLObjectElement> & { asset?: SpinnerIllustrationAsset }) {
  return (
    <object
      type="image/svg+xml"
      data={ILLUSTRATION_SRC[asset]}
      aria-hidden="true"
      className={cn(className)}
      {...props}
    />
  );
}
