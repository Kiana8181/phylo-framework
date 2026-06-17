"use client";

import { useMemo, useState } from "react";
import type {
  RunResult,
  BrepPhyloArborescence,
  BrepPhyloArborescenceEdge,
} from "@phylo/contracts";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import ResultSection from "./shared/ResultSection";
import MetricGrid from "./shared/MetricGrid";
import Facts, { StatusBadge } from "./shared/Facts";
import DataTable, { type DataColumn } from "./shared/DataTable";

type Row = Record<string, unknown>;

function autoColumns(rows: Row[]): DataColumn<Row>[] {
  const keys = rows[0] ? Object.keys(rows[0]) : [];
  return keys.map((k) => ({ key: k, header: k, className: "whitespace-nowrap px-3 py-2" }));
}

function yesNo(v: boolean | null | undefined): string {
  return v == null ? "n/a" : v ? "yes" : "no";
}

function ArborescenceSection({ arborescence }: { arborescence: BrepPhyloArborescence[] }) {
  const [cloneId, setCloneId] = useState(arborescence[0]?.clone_id ?? "");
  const selected = arborescence.find((a) => a.clone_id === cloneId) ?? arborescence[0];
  const edges = (selected?.edges ?? []) as BrepPhyloArborescenceEdge[];
  const columns: DataColumn<BrepPhyloArborescenceEdge>[] = [
    { key: "startLabel", header: "From", value: (e) => String(e.startLabel ?? e.startID ?? "") },
    { key: "endLabel", header: "To", value: (e) => String(e.endLabel ?? e.endID ?? "") },
    { key: "weight", header: "Weight", value: (e) => String(e.weight ?? "") },
  ];
  return (
    <ResultSection
      title="Arborescence"
      description="Minimum-spanning arborescence edges per clone."
      actions={
        <Select value={cloneId} onValueChange={setCloneId}>
          <SelectTrigger className="h-8 w-[180px] text-xs">
            <SelectValue placeholder="Clone" />
          </SelectTrigger>
          <SelectContent>
            {arborescence.map((a) => (
              <SelectItem key={a.clone_id} value={a.clone_id}>
                {a.clone_id}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      }
      flush
    >
      <DataTable columns={columns} rows={edges} emptyMessage="No edges for this clone." />
    </ResultSection>
  );
}

export default function BrepphyloResults({ result }: { result: RunResult }) {
  const stats = (result.stats ?? {}) as Record<string, unknown>;
  const analysis = result.analysis;
  const diagnostics = result.diagnostics;

  const csrEvents = analysis?.csr_events ?? [];
  const csrSummary = (analysis?.csr_summary ?? []) as Row[];
  const distance = analysis?.distance_from_germline ?? [];
  const isotypeValidity = analysis?.isotype_switch_validity ?? [];
  const perClone = analysis?.per_clone_status ?? [];
  const skipped = analysis?.skipped_clones ?? [];
  const arborescence = analysis?.arborescence ?? [];
  const batch = analysis?.batch_summary;

  const mixedGermline = diagnostics?.mixed_germline_clones ?? [];
  const unmappedTips = diagnostics?.unmapped_tree_tips ?? [];
  const rowIssues = useMemo(
    () => [
      ...(diagnostics?.rejected_rows ?? []).map((r) => ({ source: "rejected", ...r })),
      ...(diagnostics?.dropped_rows ?? []).map((r) => ({ source: "dropped", ...r })),
      ...(diagnostics?.unmapped_input_rows ?? []).map((r) => ({ source: "unmapped", ...r })),
    ],
    [diagnostics],
  );

  const csrFallbackRows = useMemo(
    () => Object.entries(analysis?.csr_summary_fallback ?? {}).map(([k, v]) => ({ switch: k, count: v })),
    [analysis?.csr_summary_fallback],
  );

  const csrOn = stats.enable_csr_analysis === true || csrEvents.length > 0;

  return (
    <div className="space-y-4">
      <MetricGrid
        metrics={[
          { label: "Clones", value: stats.n_clones as number },
          { label: "Trees", value: stats.n_trees as number },
          { label: "Tree inference (s)", value: stats.tree_inference_seconds as number },
          { label: "Analysis (s)", value: stats.analysis_seconds as number },
        ]}
      />

      <ResultSection
        title="BrepPhylo settings"
        description="Tree inference method and input preparation."
        badge={
          <StatusBadge tone={csrOn ? "success" : "neutral"}>
            CSR analysis {csrOn ? "on" : "off"}
          </StatusBadge>
        }
      >
        <Facts
          facts={[
            { label: "Tree type", value: (stats.tree_type ?? stats.tree_type_requested) as string },
            { label: "Input mode", value: String(stats.input_sequence_mode ?? "").replace(/_/g, " ") },
            { label: "Species", value: (stats.species_effective ?? stats.species) as string },
            { label: "Alignment", value: stats.algorithm as string },
            { label: "Plot type", value: stats.plot_type as string },
            { label: "Min clone size", value: stats.min_clone_size as number },
          ]}
        />
      </ResultSection>

      {batch && (
        <MetricGrid
          metrics={[
            { label: "Clones analyzed", value: batch.clones_analyzed },
            { label: "Clones skipped", value: batch.clones_skipped },
            { label: "CSR events", value: batch.csr_total },
            { label: "Distance rows", value: batch.distance_rows },
          ]}
        />
      )}

      {csrEvents.length > 0 && (
        <ResultSection title="Class-switch recombination events" flush>
          <DataTable
            columns={[
              { key: "clone_id", header: "Clone" },
              { key: "from_isotype", header: "From", value: (e) => String(e.from_isotype ?? "") },
              { key: "to_isotype", header: "To", value: (e) => String(e.to_isotype ?? "") },
              { key: "distance_from_germline", header: "Dist. from germline", value: (e) => String(e.distance_from_germline ?? "") },
              { key: "valid", header: "Valid switch", value: (e) => yesNo(e.valid) },
            ]}
            rows={csrEvents}
          />
        </ResultSection>
      )}

      {(csrSummary.length > 0 || csrFallbackRows.length > 0) && (
        <ResultSection title="CSR summary" flush>
          {csrSummary.length > 0 ? (
            <DataTable columns={autoColumns(csrSummary)} rows={csrSummary} />
          ) : (
            <DataTable
              columns={[
                { key: "switch", header: "Switch" },
                { key: "count", header: "Count", value: (r) => String(r.count ?? "") },
              ]}
              rows={csrFallbackRows}
            />
          )}
        </ResultSection>
      )}

      {isotypeValidity.length > 0 && (
        <ResultSection title="Isotype-switch validity" flush>
          <DataTable
            columns={[
              { key: "clone_id", header: "Clone" },
              { key: "sequence_id_from", header: "From seq", value: (r) => String(r.sequence_id_from ?? "") },
              { key: "sequence_id_to", header: "To seq", value: (r) => String(r.sequence_id_to ?? "") },
              { key: "from_isotype", header: "From", value: (r) => String(r.from_isotype ?? "") },
              { key: "to_isotype", header: "To", value: (r) => String(r.to_isotype ?? "") },
              { key: "valid", header: "Valid", value: (r) => yesNo(r.valid) },
            ]}
            rows={isotypeValidity}
          />
        </ResultSection>
      )}

      {distance.length > 0 && (
        <ResultSection title="Distance from germline" flush>
          <DataTable
            columns={[
              { key: "clone_id", header: "Clone" },
              { key: "sequence_id", header: "Sequence" },
              { key: "distance", header: "Distance", value: (r) => String(r.distance ?? "") },
            ]}
            rows={distance}
            searchable
          />
        </ResultSection>
      )}

      {perClone.length > 0 && (
        <ResultSection title="Per-clone status" flush>
          <DataTable
            columns={[
              { key: "clone_id", header: "Clone" },
              { key: "n_seqs", header: "Sequences", value: (r) => String(r.n_seqs ?? "") },
              { key: "status", header: "Status", value: (r) => String(r.status ?? (r.analyzed ? "analyzed" : "")) },
              { key: "skip_reason", header: "Skip reason", value: (r) => String(r.skip_reason ?? "") },
            ]}
            rows={perClone}
          />
        </ResultSection>
      )}

      {arborescence.length > 0 && <ArborescenceSection arborescence={arborescence} />}

      {skipped.length > 0 && (
        <ResultSection title="Skipped clones" flush>
          <DataTable
            columns={[
              { key: "clone_id", header: "Clone" },
              { key: "reason", header: "Reason" },
            ]}
            rows={skipped}
          />
        </ResultSection>
      )}

      {(rowIssues.length > 0 || mixedGermline.length > 0 || unmappedTips.length > 0 || diagnostics?.latex_available === false) && (
        <ResultSection title="Diagnostics" description="Input validation and tree-mapping issues.">
          <div className="space-y-4">
            {diagnostics?.latex_available === false && (
              <p className="rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200">
                LaTeX was not available; alignment PDF generation may have failed.
              </p>
            )}
            {rowIssues.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-medium">Row issues ({rowIssues.length})</p>
                <DataTable
                  className="rounded-lg border"
                  columns={[
                    { key: "source", header: "Source" },
                    { key: "row_index", header: "Row", value: (r) => String(r.row_index ?? "") },
                    { key: "sequence_id", header: "Sequence ID", value: (r) => String(r.sequence_id ?? "") },
                    { key: "clone_id", header: "Clone", value: (r) => String(r.clone_id ?? "") },
                    { key: "reason", header: "Reason", value: (r) => String(r.reason ?? r.label ?? "") },
                  ]}
                  rows={rowIssues}
                  searchable
                />
              </div>
            )}
            {mixedGermline.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-medium">Mixed germline per clone ({mixedGermline.length})</p>
                <DataTable
                  className="rounded-lg border"
                  columns={[
                    { key: "clone_id", header: "Clone" },
                    { key: "distinct_germlines", header: "Distinct germlines", value: (r) => (r.distinct_germlines ?? []).join(", ") },
                  ]}
                  rows={mixedGermline}
                />
              </div>
            )}
            {unmappedTips.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-medium">Unmapped tree tips ({unmappedTips.length})</p>
                <DataTable
                  className="rounded-lg border"
                  columns={[
                    { key: "clone_id", header: "Clone" },
                    { key: "final_tip_label", header: "Tip label" },
                  ]}
                  rows={unmappedTips}
                />
              </div>
            )}
          </div>
        </ResultSection>
      )}
    </div>
  );
}
