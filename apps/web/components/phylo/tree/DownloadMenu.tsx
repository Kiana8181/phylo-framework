"use client";

import { useState } from "react";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import TreeOverlay from "./TreeOverlay";

export type DownloadFormat = {
  label: string;
  description?: string;
  onSelect: () => void;
  disabled?: boolean;
};

/**
 * A single "Download" button that opens a small modal listing the available
 * export formats — replaces the previous row of per-format buttons.
 */
export default function DownloadMenu({
  formats,
  className,
}: {
  formats: DownloadFormat[];
  className?: string;
}) {
  const [open, setOpen] = useState(false);

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        className={className}
        onClick={() => setOpen(true)}
      >
        <Download className="mr-1.5 size-4" />
        Download
      </Button>

      <TreeOverlay
        open={open}
        onClose={() => setOpen(false)}
        title="Download"
        description="Choose a format to export this tree."
      >
        <div className="space-y-2">
          {formats.map((f) => (
            <button
              key={f.label}
              type="button"
              disabled={f.disabled}
              onClick={() => {
                f.onSelect();
                setOpen(false);
              }}
              className="flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition hover:bg-accent disabled:cursor-not-allowed disabled:opacity-50"
            >
              <Download className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0">
                <span className="block text-sm font-medium">{f.label}</span>
                {f.description ? (
                  <span className="block text-xs text-muted-foreground">{f.description}</span>
                ) : null}
              </span>
            </button>
          ))}
        </div>
      </TreeOverlay>
    </>
  );
}
