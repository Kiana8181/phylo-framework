import type { ReactNode } from "react";
import { Card } from "@/components/ui/card";

/** A titled results card with optional description, badge, and header actions.
 *  Pass `flush` for table content that should sit edge-to-edge (no padding). */
export default function ResultSection({
  title,
  description,
  badge,
  actions,
  flush = false,
  children,
}: {
  title: string;
  description?: ReactNode;
  badge?: ReactNode;
  actions?: ReactNode;
  flush?: boolean;
  children: ReactNode;
}) {
  return (
    <Card className="overflow-hidden p-0">
      <div className="flex flex-wrap items-start justify-between gap-2 border-b px-4 py-3">
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <h4 className="font-medium">{title}</h4>
            {badge}
          </div>
          {description ? (
            <p className="text-xs text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {actions}
      </div>
      <div className={flush ? undefined : "p-4"}>{children}</div>
    </Card>
  );
}
