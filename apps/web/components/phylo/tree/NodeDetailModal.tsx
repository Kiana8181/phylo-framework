"use client";

import { Copy } from "lucide-react";
import { notify } from "@/lib/notify";
import TreeOverlay from "./TreeOverlay";

export type NodeDetail = {
  title: string;
  rows: Array<{ key: string; value: string }>;
};

function CopyableValue({ value }: { value: string }) {
  const copy = () => {
    navigator.clipboard.writeText(value).then(
      () => notify.success("Copied"),
      () => notify.error("Copy failed"),
    );
  };
  return (
    <div className="flex min-w-0 items-center gap-1.5">
      <span className="min-w-0 flex-1 truncate font-mono text-xs" title={value}>
        {value}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy value"
        title="Copy"
        className="shrink-0 rounded p-1 text-muted-foreground transition hover:bg-accent hover:text-foreground"
      >
        <Copy className="size-3.5" />
      </button>
    </div>
  );
}

/**
 * Modal showing a clicked node's full info as a two-column (Field / Value) table.
 * Long values truncate (full text on hover) with a copy button. Open when
 * `detail` is non-null.
 */
export default function NodeDetailModal({
  detail,
  onClose,
}: {
  detail: NodeDetail | null;
  onClose: () => void;
}) {
  return (
    <TreeOverlay open={!!detail} onClose={onClose} title={detail?.title ?? "Node"}>
      {detail && detail.rows.length > 0 ? (
        <table className="w-full table-fixed text-sm">
          <thead>
            <tr className="border-b text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="w-1/3 py-2 pr-4 font-medium">Field</th>
              <th className="py-2 font-medium">Value</th>
            </tr>
          </thead>
          <tbody>
            {detail.rows.map((row) => (
              <tr key={row.key} className="border-b align-top last:border-0">
                <td className="w-1/3 py-2 pr-4 font-medium text-muted-foreground">
                  <span className="block truncate" title={row.key}>
                    {row.key}
                  </span>
                </td>
                <td className="min-w-0 py-2">
                  <CopyableValue value={row.value} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <p className="text-sm text-muted-foreground">No additional information for this node.</p>
      )}
    </TreeOverlay>
  );
}
