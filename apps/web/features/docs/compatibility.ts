// Cross-method column-compatibility model.
//
// The required / conditional classification is DERIVED from the same single
// source of truth the API preprocess step uses:
// packages/contracts/methods/<method>/columns.json (see
// apps/api/preprocess/column_requirements.py) — so the docs and the running
// validator cannot disagree. Only the column-mapping methods (dowser, gctree,
// clonaltree) declare a columns.json; BrepPhylo is not a mapping method (it
// names inputs via flat *_column params), so its requirements are derived from
// its own param.schema.required[] + ui.json, mapped to AIRR canonicals via the
// commented overlay below.

import { METHOD_IDS, type MethodId } from "./types";
import { getLoadedMethod } from "./loader";
import {
  describeCondition,
  fieldLabel,
  humanizeKey,
  type Condition,
  type LoadedMethod,
  type VisibilityRule,
} from "./model";

import dowserColumns from "@phylo/contracts/methods/dowser/columns.json";
import gctreeColumns from "@phylo/contracts/methods/gctree/columns.json";
import clonaltreeColumns from "@phylo/contracts/methods/clonaltree/columns.json";

export type ColumnStatus = "required" | "optional" | "conditional" | "not-used";

export type ColumnRequirement = {
  /** Canonical AIRR key, e.g. "sequence_id". */
  column: string;
  label: string;
  byMethod: Record<MethodId, ColumnStatus>;
  /** Human-readable reason a column is conditional in some method, if any. */
  conditionNote?: string;
};

type ColumnGroup = {
  id: string;
  note?: string;
  when?: Record<string, unknown>;
  columns: string[];
};
type ColumnsSpec = { requiredGroups: ColumnGroup[]; conditionalGroups: ColumnGroup[] };

const COLUMNS_SPEC: Partial<Record<MethodId, ColumnsSpec>> = {
  dowser: dowserColumns as ColumnsSpec,
  gctree: gctreeColumns as ColumnsSpec,
  clonaltree: clonaltreeColumns as ColumnsSpec,
};

// BrepPhylo has no column_map — it names columns via flat *_column params. This
// overlay maps those to the AIRR canonical keys the other methods share, so it
// joins the same matrix. Choices (approximate where noted):
//   sequence_column    → sequence_alignment        (aligned sequence used to build trees)
//   clone_id_column    → clone_id
//   germline_id_column → germline_alignment_d_mask (approx: germline identifier ↔ masked germline alignment)
//   label_column       → sequence_id               (per-tip label ≈ sequence identifier)
//   isotype_column     → c_call                    (isotype ↔ constant-region call; CSR-only)
const BREPPHYLO_AIRR: Record<string, string> = {
  sequence_column: "sequence_alignment",
  clone_id_column: "clone_id",
  germline_id_column: "germline_alignment_d_mask",
  label_column: "sequence_id",
  isotype_column: "c_call",
};

// Visibility conditions on these keys are wrapper/plumbing gates (is mapping
// enabled, what file format) — not biology.
const WRAPPER_GATE_KEYS = new Set(["doMapping", "$inputFormat"]);

type MethodClassification = {
  accepted: Set<string>;
  required: Set<string>;
  conditional: Map<string, string>; // canonical column -> human note
};

function conditionsOf(rule: VisibilityRule | undefined): Condition[] {
  if (!rule) return [];
  if (rule.when) return [rule.when];
  if (rule.whenAll?.length) return rule.whenAll;
  if (rule.whenAny?.length) return rule.whenAny;
  return [];
}

/** Conditions with the wrapper gates stripped out — the biological gates only. */
function biologicalConditions(rule: VisibilityRule | undefined): Condition[] {
  const result: Condition[] = [];
  for (const cond of conditionsOf(rule)) {
    const entries = Object.entries(cond).filter(([key]) => !WRAPPER_GATE_KEYS.has(key));
    if (entries.length) result.push(Object.fromEntries(entries));
  }
  return result;
}

/** column_map methods: accepted = column_map keys; required/conditional from columns.json. */
function classifyMappingMethod(m: LoadedMethod, spec: ColumnsSpec): MethodClassification {
  const columnMap = m.paramSchema.properties?.column_map?.properties ?? {};
  const accepted = new Set(Object.keys(columnMap));
  const required = new Set<string>();
  for (const group of spec.requiredGroups) for (const c of group.columns) required.add(c);
  const conditional = new Map<string, string>();
  for (const group of spec.conditionalGroups) {
    for (const c of group.columns) conditional.set(c, group.note ?? "");
  }
  // Guard against a required/conditional key not present in column_map.
  for (const c of required) accepted.add(c);
  for (const c of conditional.keys()) accepted.add(c);
  return { accepted, required, conditional };
}

/** BrepPhylo: flat *_column params → AIRR canonicals; required from param.schema.required[]. */
function classifyBrepphylo(m: LoadedMethod): MethodClassification {
  const schemaRequired = new Set(m.paramSchema.required ?? []);
  const visibility = m.uiHints.visibility ?? {};
  const accepted = new Set<string>();
  const required = new Set<string>();
  const conditional = new Map<string, string>();

  for (const [flat, canonical] of Object.entries(BREPPHYLO_AIRR)) {
    if (!m.paramSchema.properties?.[flat]) continue;
    accepted.add(canonical);
    if (schemaRequired.has(flat)) {
      required.add(canonical);
      continue;
    }
    const conds = biologicalConditions(visibility[flat]);
    if (conds.length) {
      conditional.set(canonical, conds.map((c) => describeCondition(m.paramSchema, c)).join("; "));
    }
  }
  return { accepted, required, conditional };
}

function methodClassification(id: MethodId): MethodClassification {
  const m = getLoadedMethod(id);
  const spec = COLUMNS_SPEC[id];
  return spec ? classifyMappingMethod(m, spec) : classifyBrepphylo(m);
}

/** A readable label for a canonical column, from any method's column_map title. */
function columnLabel(column: string): string {
  for (const id of METHOD_IDS) {
    const m = getLoadedMethod(id);
    if (m.paramSchema.properties?.column_map?.properties?.[column]) {
      return fieldLabel(m.paramSchema, `column_map.${column}`);
    }
  }
  return humanizeKey(column);
}

function statusFor(cls: MethodClassification, column: string): ColumnStatus {
  if (!cls.accepted.has(column)) return "not-used";
  if (cls.required.has(column)) return "required";
  if (cls.conditional.has(column)) return "conditional";
  return "optional";
}

function usageCount(row: ColumnRequirement): number {
  return Object.values(row.byMethod).filter((s) => s !== "not-used").length;
}

/**
 * The canonical columns accepted by EVERY method — the direct answer to "what
 * must my dataset contain to compare across all methods". Derived as the
 * intersection of each method's accepted column set (never hardcoded).
 */
export function getUniversalColumns(): string[] {
  const sets = METHOD_IDS.map((id) => methodClassification(id).accepted);
  if (!sets.length) return [];
  const [first, ...rest] = sets;
  return [...first].filter((column) => rest.every((set) => set.has(column))).sort();
}

/** One row per canonical column, classified per method — derived from the contracts. */
export function buildCompatibilityModel(): ColumnRequirement[] {
  const perMethod = new Map<MethodId, MethodClassification>(
    METHOD_IDS.map((id) => [id, methodClassification(id)]),
  );

  const allColumns = new Set<string>();
  for (const cls of perMethod.values()) for (const c of cls.accepted) allColumns.add(c);

  const rows: ColumnRequirement[] = [];
  for (const column of allColumns) {
    const byMethod = {} as Record<MethodId, ColumnStatus>;
    const notes = new Set<string>();
    for (const id of METHOD_IDS) {
      const cls = perMethod.get(id)!;
      const status = statusFor(cls, column);
      byMethod[id] = status;
      if (status === "conditional") {
        const note = cls.conditional.get(column);
        if (note) notes.add(note);
      }
    }
    rows.push({
      column,
      label: columnLabel(column),
      byMethod,
      conditionNote: notes.size ? [...notes].join("; ") : undefined,
    });
  }

  // Universal columns first, then most-used, then alphabetical — stable output.
  const universal = new Set(getUniversalColumns());
  rows.sort((a, b) => {
    const au = universal.has(a.column) ? 0 : 1;
    const bu = universal.has(b.column) ? 0 : 1;
    if (au !== bu) return au - bu;
    const usage = usageCount(b) - usageCount(a);
    if (usage !== 0) return usage;
    return a.column.localeCompare(b.column);
  });

  return rows;
}
