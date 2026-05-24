"use client";

import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import ArtifactsDownloadButton from "../ArtifactsDownloadButton";
import type {
  BrepPhyloAnalysis,
  BrepPhyloDiagnostics,
  BrepPhyloStats,
  DowserArtifact,
  DowserChainQc,
  DowserDtaResult,
  DowserInputQc,
  DowserTimeEvolution,
  DowserTreeDetail,
} from "@phylo/contracts";
import { useEffect, useMemo, useState } from "react";

const ROWS_PER_PAGE = 5;

type RepertoireTable = {
  filename?: string;
  columns?: string[];
  rows?: Array<Record<string, unknown>>;
  total_rows?: number;
  truncated?: boolean;
};

type CloneRow = { id: string; seqs: number | string };

function resolveArtifactBase64(
  artifact: string | { clone_bundle_zip?: string | null } | null | undefined,
): string | null {
  if (!artifact) return null;
  if (typeof artifact === "string") return artifact;
  if (typeof artifact === "object" && typeof artifact.clone_bundle_zip === "string") {
    return artifact.clone_bundle_zip;
  }
  return null;
}

export default function ResultsSummary({
  stats,
  cloneRows,
  artifact_zip_b64,
  artifact_name,
  repertoireTable,
  analysis,
  diagnostics,
  dowserDta,
  dowserTimeEvolution,
  dowserInputQc,
  dowserArtifacts,
  dowserChainQc,
  dowserTreesDetail,
}: {
  stats: BrepPhyloStats | Record<string, unknown> | null | undefined;
  cloneRows: CloneRow[];
  artifact_zip_b64: string | { clone_bundle_zip?: string | null } | null | undefined;
  artifact_name: string;
  repertoireTable?: RepertoireTable;
  analysis?: BrepPhyloAnalysis;
  diagnostics?: BrepPhyloDiagnostics;
  dowserDta?: DowserDtaResult;
  dowserTimeEvolution?: DowserTimeEvolution;
  dowserInputQc?: DowserInputQc;
  dowserArtifacts?: DowserArtifact[];
  dowserChainQc?: DowserChainQc;
  dowserTreesDetail?: DowserTreeDetail[];
}) {
  const [currentPage, setCurrentPage] = useState(1);
  const [repertoirePage, setRepertoirePage] = useState(1);
  const [tableQuery, setTableQuery] = useState("");
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");

  const artifactB64 = resolveArtifactBase64(artifact_zip_b64);

  const statsRecord = (stats ?? {}) as BrepPhyloStats;
  const csrEvents = analysis?.csr_events ?? [];
  const distanceRows = analysis?.distance_from_germline ?? [];
  const skippedClones = analysis?.skipped_clones ?? [];
  const batchSummary = analysis?.batch_summary;
  const mixedGermline = diagnostics?.mixed_germline_clones ?? [];
  const rejectedRows = diagnostics?.rejected_rows ?? [];
  const droppedRows = diagnostics?.dropped_rows ?? [];
  const unmappedInput = diagnostics?.unmapped_input_rows ?? [];

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

  const repertoireRows = useMemo(() => {
    const rows = repertoireTable?.rows;
    return Array.isArray(rows) ? rows : [];
  }, [repertoireTable?.rows]);

  const repertoireColumns = useMemo(() => {
    const columns = repertoireTable?.columns;
    if (Array.isArray(columns) && columns.length) return columns;
    if (!repertoireRows.length) return [] as string[];
    return Object.keys(repertoireRows[0] ?? {});
  }, [repertoireRows, repertoireTable?.columns]);

  const filteredRepertoireRows = useMemo(() => {
    const q = tableQuery.trim().toLowerCase();
    if (!q) return repertoireRows;
    return repertoireRows.filter((row) =>
      repertoireColumns.some((col) => String(row?.[col] ?? "").toLowerCase().includes(q)),
    );
  }, [repertoireColumns, repertoireRows, tableQuery]);

  const totalRepertoirePages = useMemo(
    () => Math.max(1, Math.ceil(filteredRepertoireRows.length / ROWS_PER_PAGE)),
    [filteredRepertoireRows.length],
  );

  const pagedRepertoireRows = useMemo(() => {
    const start = (repertoirePage - 1) * ROWS_PER_PAGE;
    return filteredRepertoireRows.slice(start, start + ROWS_PER_PAGE);
  }, [filteredRepertoireRows, repertoirePage]);

  useEffect(() => {
    setRepertoirePage(1);
  }, [tableQuery, repertoireRows]);

  useEffect(() => {
    if (repertoirePage > totalRepertoirePages) setRepertoirePage(totalRepertoirePages);
  }, [repertoirePage, totalRepertoirePages]);

  const repertoireStartRow = filteredRepertoireRows.length ? (repertoirePage - 1) * ROWS_PER_PAGE + 1 : 0;
  const repertoireEndRow = Math.min(repertoirePage * ROWS_PER_PAGE, filteredRepertoireRows.length);

  const copyRepertoireTsv = async () => {
    if (!repertoireColumns.length || !pagedRepertoireRows.length) return;
    const lines = [
      repertoireColumns.join("\t"),
      ...pagedRepertoireRows.map((row) =>
        repertoireColumns.map((col) => String(row?.[col] ?? "")).join("\t"),
      ),
    ];
    try {
      await navigator.clipboard.writeText(lines.join("\n"));
      setCopyState("copied");
      window.setTimeout(() => setCopyState("idle"), 1500);
    } catch {
      setCopyState("error");
      window.setTimeout(() => setCopyState("idle"), 1500);
    }
  };

  const hasDowserDta = Boolean(dowserDta && (dowserDta.switches?.length || dowserDta.ps?.summary?.length));
  const internalNodes = (dowserTreesDetail ?? []).flatMap((t) =>
    (t.nodes ?? []).filter((n: { is_internal?: boolean }) => n.is_internal),
  );
  const dtaSwitches = dowserDta?.switches ?? [];

  const hasAnalysis =
    Boolean(batchSummary) ||
    csrEvents.length > 0 ||
    distanceRows.length > 0 ||
    skippedClones.length > 0;

  const hasDiagnostics =
    mixedGermline.length > 0 ||
    rejectedRows.length > 0 ||
    droppedRows.length > 0 ||
    unmappedInput.length > 0 ||
    diagnostics?.latex_available === false;

  return (
    <section className="space-y-4">
      <h3 className="text-lg font-medium">Results</h3>

      {stats && (statsRecord.n_clones || statsRecord.n_trees || statsRecord.total_seqs) && (
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          {statsRecord.n_clones != null && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Clones</div>
              <div className="text-2xl font-semibold">{statsRecord.n_clones}</div>
            </Card>
          )}
          {statsRecord.n_trees != null && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Trees</div>
              <div className="text-2xl font-semibold">{statsRecord.n_trees}</div>
            </Card>
          )}
          {statsRecord.total_seqs != null && (
            <Card className="p-4">
              <div className="text-xs text-muted-foreground">Sequences</div>
              <div className="text-2xl font-semibold">{statsRecord.total_seqs}</div>
            </Card>
          )}
        </div>
      )}

      {(statsRecord as Record<string, unknown>).canonical_ids === "sequence_id" && (
        <p className="text-xs text-muted-foreground rounded border px-3 py-2 bg-muted/20">
          Canonical tree identifiers use <code>sequence_id</code>. Display labels (if configured) do not replace
          canonical Newick.
        </p>
      )}

      {hasDowserDta && dowserDta && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Discrete trait analysis</h4>
            <p className="text-xs text-yellow-800 dark:text-yellow-200 mt-1">
              {dowserDta.interpretation_warning ??
                "Significant directional trait association is evidence consistent with migration/differentiation/class switching, not proof."}
            </p>
          </div>
          {dtaSwitches.length > 0 && (
            <div className="overflow-x-auto border-b">
              <table className="w-full text-xs">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left">From</th>
                    <th className="px-3 py-2 text-left">To</th>
                    <th className="px-3 py-2 text-left">Count</th>
                  </tr>
                </thead>
                <tbody>
                  {dtaSwitches.slice(0, 30).map((sw: Record<string, unknown>, idx: number) => (
                    <tr key={`dta-sw-${idx}`} className="border-t">
                      <td className="px-3 py-2">{String(sw.from ?? sw.FROM ?? "—")}</td>
                      <td className="px-3 py-2">{String(sw.to ?? sw.TO ?? "—")}</td>
                      <td className="px-3 py-2">{String(sw.count ?? sw.N ?? "—")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {dowserTimeEvolution && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Time evolution</h4>
            <p className="text-xs text-yellow-800 dark:text-yellow-200 mt-1">
              {dowserTimeEvolution.interpretation_warning ??
                "Correlation with sampling time suggests measurable evolution, but depends on sampling design and tree uncertainty."}
            </p>
          </div>
          <div className="px-4 py-3 text-xs text-muted-foreground">
            Time field: {dowserTimeEvolution.time_field ?? "—"} · Permutations:{" "}
            {dowserTimeEvolution.permutations ?? "—"} · Results:{" "}
            {dowserTimeEvolution.results?.length ?? 0}
          </div>
        </Card>
      )}

      {internalNodes.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Internal node sequences</h4>
            <p className="text-xs text-muted-foreground mt-1">
              Showing first {Math.min(10, internalNodes.length)} reconstructed internal nodes.
            </p>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-muted/40">
                <tr>
                  <th className="px-3 py-2 text-left">Clone</th>
                  <th className="px-3 py-2 text-left">Node</th>
                  <th className="px-3 py-2 text-left">Locus</th>
                  <th className="px-3 py-2 text-left">Sequence (prefix)</th>
                </tr>
              </thead>
              <tbody>
                {internalNodes.slice(0, 10).map((n, idx) => (
                  <tr key={`int-${idx}`} className="border-t">
                    <td className="px-3 py-2">{n.clone_id ?? "—"}</td>
                    <td className="px-3 py-2">{n.node_id ?? n.node ?? "—"}</td>
                    <td className="px-3 py-2">{n.locus ?? "—"}</td>
                    <td className="px-3 py-2 font-mono">
                      {String(n.sequence ?? n.sequence_alignment ?? "").slice(0, 40)}
                      {String(n.sequence ?? n.sequence_alignment ?? "").length > 40 ? "…" : ""}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

      {(dowserInputQc || dowserChainQc) && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Input QC</h4>
          </div>
          <div className="px-4 py-3 text-xs space-y-1 text-muted-foreground">
            {dowserInputQc?.n_input_rows != null && (
              <div>Input rows: {dowserInputQc.n_input_rows} → working: {dowserInputQc.n_working_rows ?? "—"}</div>
            )}
            {dowserInputQc?.n_length_mismatch != null && dowserInputQc.n_length_mismatch > 0 && (
              <div className="text-yellow-800 dark:text-yellow-200">
                Length mismatches: {dowserInputQc.n_length_mismatch}
              </div>
            )}
            {dowserInputQc?.n_excluded_trait_missing != null && dowserInputQc.n_excluded_trait_missing > 0 && (
              <div>Excluded missing trait: {dowserInputQc.n_excluded_trait_missing}</div>
            )}
            {dowserChainQc?.chain_mode === "HL" && (
              <div>
                Paired H/L: {dowserChainQc.n_after_resolve ?? "—"} rows retained (
                {dowserChainQc.n_dropped ?? 0} dropped)
              </div>
            )}
          </div>
        </Card>
      )}

      {dowserArtifacts && dowserArtifacts.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Export artifacts</h4>
            <p className="text-xs text-muted-foreground mt-1">
              Machine-readable outputs produced during the run.
            </p>
          </div>
          <ul className="px-4 py-3 text-sm space-y-1">
            {dowserArtifacts.map((a, idx) => (
              <li key={`art-${idx}`} className="font-mono text-xs">
                {a.name ?? a.path ?? "artifact"} ({a.kind ?? "file"})
              </li>
            ))}
          </ul>
        </Card>
      )}

      {hasAnalysis && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">CSR / lineage analysis</h4>
            {batchSummary && (
              <p className="text-xs text-muted-foreground mt-1">
                Analyzed {batchSummary.clones_analyzed ?? 0} clone(s); skipped{" "}
                {batchSummary.clones_skipped ?? 0}; CSR events {batchSummary.csr_total ?? 0}; distance rows{" "}
                {batchSummary.distance_rows ?? 0}
              </p>
            )}
          </div>
          {csrEvents.length > 0 && (
            <div className="overflow-x-auto border-b">
              <table className="w-full text-xs">
                <thead className="bg-muted/40">
                  <tr>
                    <th className="px-3 py-2 text-left">Clone</th>
                    <th className="px-3 py-2 text-left">From</th>
                    <th className="px-3 py-2 text-left">To</th>
                    <th className="px-3 py-2 text-left">Dist. from germline</th>
                    <th className="px-3 py-2 text-left">Valid switch</th>
                  </tr>
                </thead>
                <tbody>
                  {csrEvents.slice(0, 50).map((ev, idx) => (
                    <tr key={`csr-${idx}`} className="border-t">
                      <td className="px-3 py-2">{ev.clone_id}</td>
                      <td className="px-3 py-2">{ev.from_isotype ?? "—"}</td>
                      <td className="px-3 py-2">{ev.to_isotype ?? "—"}</td>
                      <td className="px-3 py-2">
                        {ev.distance_from_germline != null ? ev.distance_from_germline : "—"}
                      </td>
                      <td className="px-3 py-2">
                        {ev.valid == null ? "n/a" : ev.valid ? "yes" : "no"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {csrEvents.length > 50 && (
                <div className="px-4 py-2 text-xs text-muted-foreground">
                  Showing first 50 of {csrEvents.length} CSR events.
                </div>
              )}
            </div>
          )}
          {skippedClones.length > 0 && (
            <div className="px-4 py-3 text-xs space-y-1">
              <div className="font-medium">Skipped clones</div>
              {skippedClones.map((s, idx) => (
                <div key={`skip-${idx}`} className="text-muted-foreground">
                  {s.clone_id}: {s.reason}
                </div>
              ))}
            </div>
          )}
        </Card>
      )}

      {hasDiagnostics && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Diagnostics</h4>
          </div>
          <div className="px-4 py-3 text-xs space-y-3">
            {diagnostics?.latex_available === false && (
              <p className="text-yellow-800 dark:text-yellow-200">
                LaTeX was not available; alignment PDF generation may have failed.
              </p>
            )}
            {mixedGermline.length > 0 && (
              <div>
                <div className="font-medium mb-1">Mixed germline per clone ({mixedGermline.length})</div>
                {mixedGermline.slice(0, 10).map((m, idx) => (
                  <div key={`mixed-${idx}`} className="text-muted-foreground">
                    {m.clone_id}: {(m.distinct_germlines ?? []).join(", ")}
                  </div>
                ))}
              </div>
            )}
            {[...rejectedRows, ...droppedRows, ...unmappedInput].length > 0 && (
              <div>
                <div className="font-medium mb-1">Row issues</div>
                {[...rejectedRows, ...droppedRows, ...unmappedInput].slice(0, 15).map((r, idx) => (
                  <div key={`row-${idx}`} className="text-muted-foreground">
                    row {r.row_index}
                    {r.sequence_id ? ` (${r.sequence_id})` : ""}
                    {r.reason ? `: ${r.reason}` : ""}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Card>
      )}

      {cloneRows.length ? (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b">
            <h4 className="font-medium">Clone summary</h4>
          </div>
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
        </Card>
      ) : null}

      {repertoireRows.length > 0 && (
        <Card className="p-0 overflow-hidden">
          <div className="px-4 py-3 border-b flex items-center justify-between gap-3">
            <div>
              <h4 className="font-medium">Other outputs / Tables</h4>
              <p className="text-xs text-muted-foreground">
                {repertoireTable?.filename || "repertoire_two_levels_info.tsv"}
              </p>
            </div>
            <Button variant="outline" size="sm" onClick={copyRepertoireTsv}>
              {copyState === "copied" ? "Copied" : copyState === "error" ? "Copy failed" : "Copy visible rows"}
            </Button>
          </div>
          <div className="px-4 py-3 border-b flex flex-col sm:flex-row gap-3 sm:items-center sm:justify-between">
            <Input
              value={tableQuery}
              onChange={(e) => setTableQuery(e.target.value)}
              placeholder="Search table..."
              className="sm:max-w-xs"
            />
            <div className="text-xs text-muted-foreground">
              Showing {repertoireStartRow}-{repertoireEndRow} of {filteredRepertoireRows.length} filtered (
              {repertoireRows.length} total)
            </div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="bg-muted/40">
                <tr>
                  {repertoireColumns.map((col) => (
                    <th key={col} className="px-3 py-2 text-left whitespace-nowrap">
                      {col}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {pagedRepertoireRows.map((row, rowIdx) => (
                  <tr
                    key={`repertoire-row-${(repertoirePage - 1) * ROWS_PER_PAGE + rowIdx}`}
                    className="border-t align-top"
                  >
                    {repertoireColumns.map((col) => (
                      <td key={`${rowIdx}-${col}`} className="px-3 py-2 whitespace-nowrap">
                        {String(row?.[col] ?? "")}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {filteredRepertoireRows.length > ROWS_PER_PAGE && (
            <div className="flex items-center justify-between gap-3 border-t px-4 py-3 text-sm">
              <div className="text-muted-foreground">
                Page {repertoirePage} of {totalRepertoirePages}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setRepertoirePage((p) => Math.max(1, p - 1))}
                  disabled={repertoirePage === 1}
                >
                  Previous
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setRepertoirePage((p) => Math.min(totalRepertoirePages, p + 1))}
                  disabled={repertoirePage === totalRepertoirePages}
                >
                  Next
                </Button>
              </div>
            </div>
          )}
          {repertoireTable?.truncated && (
            <div className="px-4 py-2 border-t text-xs text-muted-foreground">
              Preview truncated to {repertoireRows.length} rows (total{" "}
              {repertoireTable?.total_rows ?? repertoireRows.length}).
            </div>
          )}
        </Card>
      )}

      {artifactB64 && <ArtifactsDownloadButton base64={artifactB64} filename={artifact_name} />}
    </section>
  );
}
