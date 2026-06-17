"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { ClipboardCopy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { notify } from "@/lib/notify";

export type DataColumn<T> = {
  key: string;
  header: string;
  /** Custom cell renderer. Defaults to the stringified `key` value. */
  render?: (row: T) => ReactNode;
  /** Plain-text value used for search/copy. Defaults to the stringified `key` value. */
  value?: (row: T) => string;
  className?: string;
};

function defaultValue<T>(row: T, key: string): string {
  const v = (row as Record<string, unknown>)[key];
  return v == null ? "" : String(v);
}

/**
 * Generic, always-paginated results table. Optional client-side search and
 * "copy visible rows" (TSV). One component for every results table so they all
 * paginate consistently.
 */
export default function DataTable<T>({
  columns,
  rows,
  pageSize = 10,
  searchable = false,
  copyable = false,
  emptyMessage = "No rows.",
  className,
}: {
  columns: DataColumn<T>[];
  rows: T[];
  pageSize?: number;
  searchable?: boolean;
  copyable?: boolean;
  emptyMessage?: string;
  className?: string;
}) {
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState("");

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter((row) =>
      columns.some((col) =>
        (col.value ? col.value(row) : defaultValue(row, col.key)).toLowerCase().includes(q),
      ),
    );
  }, [columns, rows, query]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));

  useEffect(() => {
    setPage(1);
  }, [query, rows]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  const start = (page - 1) * pageSize;
  const pageRows = filtered.slice(start, start + pageSize);
  const startRow = filtered.length ? start + 1 : 0;
  const endRow = Math.min(start + pageSize, filtered.length);

  const copyVisible = async () => {
    const lines = [
      columns.map((c) => c.header).join("\t"),
      ...pageRows.map((row) =>
        columns.map((c) => (c.value ? c.value(row) : defaultValue(row, c.key))).join("\t"),
      ),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      notify.success("Copied visible rows");
    } catch {
      notify.error("Copy failed");
    }
  };

  return (
    <div className={className}>
      {(searchable || copyable) && (
        <div className="flex flex-col gap-2 border-b px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
          {searchable ? (
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search table…"
              className="sm:max-w-xs"
            />
          ) : (
            <span />
          )}
          {copyable && (
            <Button variant="outline" size="sm" onClick={copyVisible} className="gap-1.5">
              <ClipboardCopy className="size-3.5" />
              Copy visible rows
            </Button>
          )}
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead className="bg-muted/40">
            <tr>
              {columns.map((col) => (
                <th key={col.key} className="whitespace-nowrap px-3 py-2 text-left font-medium">
                  {col.header}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {pageRows.length === 0 ? (
              <tr>
                <td colSpan={columns.length} className="px-3 py-6 text-center text-muted-foreground">
                  {emptyMessage}
                </td>
              </tr>
            ) : (
              pageRows.map((row, rowIdx) => (
                <tr key={`row-${start + rowIdx}`} className="border-t align-top">
                  {columns.map((col) => (
                    <td key={col.key} className={col.className ?? "px-3 py-2"}>
                      {col.render ? col.render(row) : defaultValue(row, col.key)}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t px-4 py-3 text-xs">
        <span className="text-muted-foreground">
          {filtered.length ? `Showing ${startRow}–${endRow} of ${filtered.length}` : "No rows"}
          {query.trim() && rows.length !== filtered.length ? ` (filtered from ${rows.length})` : ""}
        </span>
        {totalPages > 1 && (
          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page === 1}
            >
              Previous
            </Button>
            <span className="text-muted-foreground">
              Page {page} of {totalPages}
            </span>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page === totalPages}
            >
              Next
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
