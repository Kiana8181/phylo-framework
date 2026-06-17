import Link from "next/link";
import { GitBranch } from "lucide-react";
import { cn } from "@/lib/utils";

type PhyloLogoProps = {
  collapsed?: boolean;
  className?: string;
};

export function PhyloLogo({ collapsed = false, className }: PhyloLogoProps) {
  return (
    <Link
      href="/dashboard"
      className={cn(
        "group flex items-center gap-2.5 rounded-lg transition-colors hover:text-primary min-w-0",
        collapsed ? "justify-center px-1" : "px-1",
        className,
      )}
      title={collapsed ? "Phylo Framework" : undefined}
    >
      <span className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gradient-to-br from-primary to-chart-2 shadow-sm">
        <GitBranch className="h-4 w-4 text-primary-foreground" strokeWidth={2.5} />
      </span>
      {!collapsed && (
        <span className="flex min-w-0 flex-col leading-tight">
          <span className="truncate text-sm font-semibold tracking-tight text-foreground group-hover:text-primary">
            PhyloFramework
          </span>
          <span className="truncate text-[10px] font-medium uppercase tracking-widest text-muted-foreground">
            BCR Lineage Platform
          </span>
        </span>
      )}
    </Link>
  );
}
