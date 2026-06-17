import { Loader2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { SpinnerIllustration, type SpinnerIllustrationAsset } from "@/components/ui/spinner-illustration";

type LoadingSize = "sm" | "md" | "lg";
type LoadingVariant = "spinner" | "illustration";

const GLYPH_SIZE: Record<LoadingSize, string> = {
  sm: "size-4",
  md: "size-8",
  lg: "size-14",
};

/** Illustration asset is wider (4:3); give it more room than the compact spinner. */
const ILLUSTRATION_SIZE: Record<LoadingSize, string> = {
  sm: "h-36 w-38",
  md: "h-30 w-44",
  lg: "h-48 w-52",
};

const LABEL_SIZE: Record<LoadingSize, string> = {
  sm: "text-xs",
  md: "text-sm",
  lg: "text-sm",
};

export interface SpinnerProps {
  /** Glyph dimensions. Defaults to `sm` for inline/button use. */
  size?: LoadingSize;
  className?: string;
}

/**
 * Compact, theme-aware spinning indicator for inline and in-button use.
 * Renders just the glyph (no wrapper), so it sits next to text naturally.
 */
export function Spinner({ size = "sm", className }: SpinnerProps) {
  return <Loader2 className={cn(GLYPH_SIZE[size], "animate-spin", className)} aria-hidden="true" />;
}

export interface LoadingProps {
  /** Visual treatment. `illustration` shows the animated loading asset
   *  (best for section/page loads); `spinner` shows a compact lucide spinner.
   *  Defaults to `illustration`. */
  variant?: LoadingVariant;
  /** Controls the glyph dimensions. Defaults to `lg`. */
  size?: LoadingSize;
  /** Optional caption rendered beneath the glyph. */
  label?: string;
  /** Which illustration asset to show when `variant` is `illustration`. */
  illustration?: SpinnerIllustrationAsset;
  /** Center the loader in a full-viewport-height region. */
  fullScreen?: boolean;
  /** Extra classes for the wrapping element. */
  className?: string;
}

/**
 * Shared, theme-aware block loading indicator for section and page loads.
 * Renders in `text-primary` so it picks up the purple theme in both modes.
 */
export function Loading({
  variant = "illustration",
  size = "lg",
  illustration = "default",
  label,
  fullScreen = false,
  className,
}: LoadingProps) {
  const glyphClass = cn(
    variant === "illustration" ? ILLUSTRATION_SIZE[size] : GLYPH_SIZE[size],
    "text-primary",
  );

  return (
    <div
      role="status"
      aria-live="polite"
      className={cn(
        "flex flex-col items-center justify-center gap-3",
        fullScreen ? "min-h-[calc(100vh-3.5rem)] w-full" : "py-12",
        className,
      )}
    >
      {variant === "illustration" ? (
        <SpinnerIllustration className={glyphClass} asset={illustration} />
      ) : (
        <Loader2 className={cn(glyphClass, "animate-spin")} aria-hidden="true" />
      )}
      {label ? (
        <p
          className={cn("text-muted-foreground", LABEL_SIZE[size])}
          dir="ltr"
          suppressHydrationWarning
        >
          {label}
        </p>
      ) : null}
      <span className="sr-only">{label ?? "Loading"}</span>
    </div>
  );
}
