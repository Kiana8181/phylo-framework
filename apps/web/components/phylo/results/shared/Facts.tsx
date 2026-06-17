import { cn } from "@/lib/utils";

export type Fact = { label: string; value: string | number | null | undefined };

/** Compact label→value grid for run facts (parameters, modes, thresholds). */
export default function Facts({ facts, className }: { facts: Fact[]; className?: string }) {
  const shown = facts.filter((f) => f.value != null && f.value !== "");
  if (!shown.length) return null;
  return (
    <div className={cn("grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-3 lg:grid-cols-4", className)}>
      {shown.map((f) => (
        <div key={f.label} className="min-w-0">
          <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{f.label}</p>
          <p className="break-words text-sm">{String(f.value)}</p>
        </div>
      ))}
    </div>
  );
}

/** Small status pill used in section headers. */
export function StatusBadge({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: "neutral" | "success" | "warning" | "danger";
}) {
  const tones: Record<string, string> = {
    neutral: "bg-muted text-muted-foreground",
    success: "bg-green-500/15 text-green-700 dark:text-green-400",
    warning: "bg-amber-500/15 text-amber-700 dark:text-amber-400",
    danger: "bg-destructive/15 text-destructive",
  };
  return (
    <span className={cn("inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium", tones[tone])}>
      {children}
    </span>
  );
}
