import type { RunResult } from "@phylo/contracts";
import ResultSection from "./shared/ResultSection";
import MetricGrid from "./shared/MetricGrid";
import Facts from "./shared/Facts";
import DataTable, { type DataColumn } from "./shared/DataTable";

type Row = Record<string, unknown>;

function autoColumns(rows: Row[]): DataColumn<Row>[] {
  const keys = rows[0] ? Object.keys(rows[0]) : [];
  return keys.map((k) => ({ key: k, header: k, className: "whitespace-nowrap px-3 py-2" }));
}

const WARN_CLASS =
  "rounded border border-amber-300 bg-amber-50 px-3 py-2 text-xs text-amber-900 dark:border-amber-800 dark:bg-amber-950/30 dark:text-amber-200";

const numVal = (v: unknown): number | undefined =>
  typeof v === "number" && Number.isFinite(v) ? v : undefined;
const arrLen = (v: unknown): number | undefined => (Array.isArray(v) ? v.length : undefined);

/** IgPhyML emits per-clone MLE parameters under `parameters.parameters[cloneId]`
 *  (sometimes one level shallower). Flatten to one row per clone. */
function igphymlRows(parameters: unknown): Row[] {
  if (!parameters || typeof parameters !== "object") return [];
  const outer = parameters as Record<string, unknown>;
  const inner =
    outer.parameters && typeof outer.parameters === "object" && !Array.isArray(outer.parameters)
      ? (outer.parameters as Record<string, unknown>)
      : outer;
  return Object.values(inner).filter(
    (v): v is Row => v != null && typeof v === "object" && !Array.isArray(v),
  );
}

export default function DowserResults({ result }: { result: RunResult }) {
  const stats = (result.stats ?? {}) as Record<string, unknown>;
  const dta = result.discrete_trait_analysis;
  const time = result.time_evolution;
  const qc = (result.input_qc ?? {}) as Record<string, unknown>;
  const chainQc = result.chain_qc;
  const igphyml = result.igphyml;
  const igExtra = (igphyml ?? {}) as Record<string, unknown>;

  const dtaSwitches = (dta?.switches ?? []) as Row[];
  const ps = (dta?.ps?.summary ?? []) as Row[];
  const sp = (dta?.sp?.summary ?? []) as Row[];
  const sc = (dta?.sc?.summary ?? []) as Row[];
  const timeResults = (time?.results ?? []) as Row[];
  const igRows = igphymlRows(igphyml?.parameters);

  const hasDta = dtaSwitches.length > 0 || ps.length > 0 || sp.length > 0 || sc.length > 0;

  return (
    <div className="space-y-4">
      <MetricGrid
        metrics={[
          { label: "Clones", value: stats.n_clones as number },
          { label: "Trees", value: stats.n_trees as number },
          { label: "Sequences", value: stats.total_seqs as number },
        ]}
      />

      <ResultSection title="Dowser settings" description="How trees were built and what analysis was run.">
        <Facts
          facts={[
            { label: "Analysis mode", value: String(stats.analysis_mode ?? "").replace(/_/g, " ") },
            { label: "Tree build", value: stats.tree_build as string },
            { label: "Canonical IDs", value: stats.canonical_ids as string },
          ]}
        />
      </ResultSection>

      {(Object.keys(qc).length > 0 || chainQc?.chain_mode === "HL") && (
        <ResultSection title="Input QC" description="Records and clones retained through each validation stage.">
          <Facts
            facts={[
              { label: "Rows (input)", value: numVal(qc.n_rows_original) ?? numVal(qc.n_input_rows) },
              { label: "Rows (after derived fields)", value: numVal(qc.n_rows_after_derived_fields) },
              { label: "Rows (after trait exclusion)", value: numVal(qc.n_rows_after_trait_exclusion) ?? numVal(qc.n_working_rows) },
              { label: "Clones (input)", value: numVal(qc.n_clones_original) ?? numVal(qc.n_clones_input) },
              { label: "Clones (after formatClones)", value: numVal(qc.n_clones_after_formatClones) },
              { label: "Clones (after trait exclusion)", value: numVal(qc.n_clones_after_trait_exclusion) ?? numVal(qc.n_clones_working) },
              { label: "Duplicate seq IDs", value: arrLen(qc.duplicate_sequence_ids) ?? numVal(qc.n_duplicate_sequence_id) },
              { label: "Length mismatches", value: arrLen(qc.length_mismatch) ?? numVal(qc.n_length_mismatch) },
              { label: "Excluded (missing trait)", value: arrLen(qc.excluded_missing_trait) ?? numVal(qc.n_excluded_trait_missing) },
              ...(chainQc?.chain_mode === "HL"
                ? [
                    { label: "Paired H/L retained", value: chainQc?.n_after_resolve },
                    { label: "H/L dropped", value: chainQc?.n_dropped },
                  ]
                : []),
            ]}
          />
        </ResultSection>
      )}

      {hasDta && (
        <ResultSection
          title="Discrete trait analysis"
          description={
            dta?.interpretation_warning ??
            "Significant directional trait association is evidence consistent with migration/differentiation/class switching, not proof."
          }
        >
          <div className="space-y-4">
            {dtaSwitches.length > 0 && (
              <div>
                <p className="mb-2 text-sm font-medium">Switches</p>
                <DataTable
                  className="rounded-lg border"
                  columns={[
                    { key: "FROM", header: "From", value: (r) => String(r.from ?? r.FROM ?? "") },
                    { key: "TO", header: "To", value: (r) => String(r.to ?? r.TO ?? "") },
                    {
                      key: "SWITCHES",
                      header: "Count",
                      value: (r) => String(r.SWITCHES ?? r.N ?? r.SWITCHES ?? ""),
                    },
                  ]}
                  rows={dtaSwitches}
                />
              </div>
            )}
            {[
              { label: "PS (parsimony) summary", rows: ps },
              { label: "SP summary", rows: sp },
              { label: "SC summary", rows: sc },
            ]
              .filter((t) => t.rows.length > 0)
              .map((t) => (
                <div key={t.label}>
                  <p className="mb-2 text-sm font-medium">{t.label}</p>
                  <DataTable className="rounded-lg border" columns={autoColumns(t.rows)} rows={t.rows} />
                </div>
              ))}
          </div>
        </ResultSection>
      )}

      {(timeResults.length > 0 || time) && (
        <ResultSection
          title="Time evolution"
          description={
            time?.interpretation_warning ??
            "Correlation with sampling time suggests measurable evolution, but depends on sampling design and tree uncertainty."
          }
          flush={timeResults.length > 0}
        >
          {timeResults.length > 0 ? (
            <DataTable columns={autoColumns(timeResults)} rows={timeResults} />
          ) : (
            <p className="text-xs text-muted-foreground">
              Time field: {time?.time_field ?? "—"} · Permutations: {time?.permutations ?? "—"}
            </p>
          )}
        </ResultSection>
      )}

      {igphyml && (igRows.length > 0 || (igphyml.warnings?.length ?? 0) > 0) && (
        <ResultSection title="IgPhyML" description="Maximum-likelihood substitution-model fit per clone.">
          <div className="space-y-4">
            <Facts
              facts={[
                {
                  label: "Partition model",
                  value: (igExtra.effective_partition_model ?? igExtra.partition_model) as string,
                },
                { label: "Requested", value: igExtra.partition_model_requested as string },
                {
                  label: "Supported",
                  value:
                    igExtra.partition_model_supported == null
                      ? undefined
                      : igExtra.partition_model_supported
                        ? "yes"
                        : "no",
                },
              ]}
            />
            {igRows.length > 0 && (
              <DataTable className="rounded-lg border" columns={autoColumns(igRows)} rows={igRows} searchable />
            )}
            {(igphyml.warnings ?? []).map((w, i) => (
              <p key={`igw-${i}`} className={WARN_CLASS}>
                {w}
              </p>
            ))}
          </div>
        </ResultSection>
      )}
    </div>
  );
}
