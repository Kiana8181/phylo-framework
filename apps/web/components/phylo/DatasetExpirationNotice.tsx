"use client";

import { Button } from "@/components/ui/button";
import type { FileSummary } from "@phylo/contracts";
import { CalendarClock } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

const DISMISS_KEY = "phylo_dataset_expiry_dismissed";

function expiryLabel(iso: string | null | undefined): string {
  if (!iso) return "";
  const time = Date.parse(iso);
  if (Number.isNaN(time)) return "";
  return new Date(time).toLocaleString();
}

function idSet(datasets: FileSummary[]): string {
  return datasets.map((dataset) => dataset.id).sort().join("\n");
}

/**
 * Persistent dashboard warning for datasets the backend marked as approaching
 * expiration. Eligibility is not calculated here. Dismissing hides the current
 * set for this browser session only; a later visit, or a new dataset entering
 * the window, shows it again.
 */
export default function DatasetExpirationNotice({ datasets }: { datasets: FileSummary[] }) {
  const key = idSet(datasets);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    try {
      setHidden(sessionStorage.getItem(DISMISS_KEY) === key);
    } catch {
      setHidden(false);
    }
  }, [key]);

  if (datasets.length === 0 || hidden) return null;

  const dismiss = () => {
    try {
      sessionStorage.setItem(DISMISS_KEY, key);
    } catch {
      /* the banner still hides for this render via state */
    }
    setHidden(true);
  };

  return (
    <div
      data-testid="dataset-expiration"
      role="status"
      className="flex items-start gap-2 rounded border border-amber-200 bg-amber-50 p-3 text-sm text-amber-950 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-100"
    >
      <CalendarClock className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1 space-y-2">
        <ul className="space-y-1">
          {datasets.map((dataset) => {
            const when = expiryLabel(dataset.expires_at);
            return (
              <li key={dataset.id}>
                Your dataset <span className="font-medium">{dataset.original_filename}</span> is approaching its
                expiration date{when ? ` (${when})` : ""} and will be automatically deleted soon. If you still need
                this dataset, visit File Management to renew it.
              </li>
            );
          })}
        </ul>
        <div className="flex flex-wrap items-center gap-2">
          <Button variant="outline" size="sm" asChild>
            <Link href="/dashboard/files">File management</Link>
          </Button>
          <Button variant="ghost" size="sm" onClick={dismiss}>
            Dismiss
          </Button>
        </div>
      </div>
    </div>
  );
}
