"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import ArtifactsDownloadButton from "../ArtifactsDownloadButton";
import { useEffect, useMemo, useState } from "react";

const ROWS_PER_PAGE = 5;

export default function ResultsSummary({
  stats,
  cloneRows,
  artifact_zip_b64,
  artifact_name,
}: {
  stats: any;
  cloneRows: Array<{ id: string; seqs: any }>;
  artifact_zip_b64: any;
  artifact_name: string;
}) {
  const [currentPage, setCurrentPage] = useState(1);

  const totalPages = useMemo(
    () => Math.max(1, Math.ceil(cloneRows.length / ROWS_PER_PAGE)),
    [cloneRows.length],
  );

  const pagedCloneRows = useMemo(() => {
    const start = (currentPage - 1) * ROWS_PER_PAGE;
    return cloneRows.slice(start, start + ROWS_PER_PAGE);
  }, [cloneRows, currentPage]);

  useEffect(() => {
    setCurrentPage(1);
  }, [cloneRows]);

  useEffect(() => {
    if (currentPage > totalPages) setCurrentPage(totalPages);
  }, [currentPage, totalPages]);

  const startRow = cloneRows.length ? (currentPage - 1) * ROWS_PER_PAGE + 1 : 0;
  const endRow = Math.min(currentPage * ROWS_PER_PAGE, cloneRows.length);

  return (
    <section className="space-y-4">
      <h3 className="text-lg font-medium">Results</h3>

      {/* KPIs */}
      {stats && (stats.n_clones || stats.n_trees || stats.total_seqs) && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {stats.n_clones && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Clones</div>
              <div className="text-2xl font-semibold">{stats.n_clones ?? "-"}</div>
            </Card>
          )}
          {stats.n_trees && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Trees</div>
              <div className="text-2xl font-semibold">{stats.n_trees ?? "-"}</div>
            </Card>
          )}
          {stats.total_seqs && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Sequences</div>
              <div className="text-2xl font-semibold">{stats.total_seqs ?? "-"}</div>
            </Card>
          )}
        </div>
      )}

      {/* Clones table */}
      {cloneRows.length ? (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Clone summary</h4>
          </div>
          {cloneRows.length ? (
            <>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left">Clone ID</th>
                      <th className="px-3 py-2 text-left">Seqs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedCloneRows.map((r, i) => (
                      <tr key={`${r.id}-${(currentPage - 1) * ROWS_PER_PAGE + i}`} className="border-t">
                        <td className="px-3 py-2">{r.id}</td>
                        <td className="px-3 py-2">{r.seqs}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {cloneRows.length > ROWS_PER_PAGE && (
                <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm">
                  <div className="text-muted-foreground">
                    Showing {startRow}-{endRow} of {cloneRows.length}
                  </div>
                  <div className="flex items-center gap-2">
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.max(1, p - 1))}
                      disabled={currentPage === 1}
                    >
                      Previous
                    </Button>
                    <span className="text-muted-foreground">
                      Page {currentPage} of {totalPages}
                    </span>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => setCurrentPage((p) => Math.min(totalPages, p + 1))}
                      disabled={currentPage === totalPages}
                    >
                      Next
                    </Button>
                  </div>
                </div>
              )}
            </>
          ) : (
            <div className="p-4 text-sm text-muted-foreground">No clone metadata found.</div>
          )}
        </Card>
      ) : null}

      {artifact_zip_b64 && <ArtifactsDownloadButton base64={artifact_zip_b64} filename={artifact_name} />}
    </section>
  );
}
