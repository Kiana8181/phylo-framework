// Builds a MethodDocModel from a loaded method (param.schema.json + ui.json).
// This is the single source of truth for the per-method field tables: the same
// JSON the live FormBuilder consumes is read here at build time, so the docs
// cannot drift from the form.

import type { DocField, DocSection, MethodContent, MethodDocModel, MethodId } from "./types";

// ---- Minimal structural types for the contracts JSON ------------------------

type JsonSchemaField = {
  type?: string;
  title?: string;
  description?: string;
  enum?: Array<string | number | boolean>;
  default?: unknown;
  minimum?: number;
  maximum?: number;
  deprecated?: boolean;
  properties?: Record<string, JsonSchemaField>;
};

export type ParamSchema = {
  type?: string;
  properties?: Record<string, JsonSchemaField>;
  required?: string[];
};

export type Condition = Record<string, unknown>;

export type VisibilityRule = {
  when?: Condition;
  whenAll?: Condition[];
  whenAny?: Condition[];
};

type UiSection = { id: string; label: string; order: number; fields: string[] };

export type UiHints = {
  order?: string[];
  sections?: UiSection[];
  visibility?: Record<string, VisibilityRule>;
  validation?: {
    requiredWhen?: Array<{ field: string; when: Condition; message?: string }>;
    mutuallyExclusive?: Array<{ fields: string[]; message?: string }>;
  };
};

export type LoadedMethod = {
  id: MethodId;
  name: string;
  acceptFormats: string[];
  paramSchema: ParamSchema;
  uiHints: UiHints;
};

// ---- Helpers ----------------------------------------------------------------

/** Resolve a (possibly nested, dot-separated) field path to its leaf schema. */
export function resolveField(schema: ParamSchema, path: string): JsonSchemaField | undefined {
  const parts = path.split(".");
  let node: JsonSchemaField | undefined = schema.properties?.[parts[0]];
  for (let i = 1; i < parts.length && node; i += 1) {
    node = node.properties?.[parts[i]];
  }
  return node;
}

/** Turn a snake_case / dotted key into a readable label as a last resort. */
export function humanizeKey(key: string): string {
  const tail = key.split(".").pop() ?? key;
  return tail
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

const SPECIAL_FIELD_LABELS: Record<string, string> = {
  $inputFormat: "Input file format",
};

export function fieldLabel(schema: ParamSchema, path: string): string {
  if (SPECIAL_FIELD_LABELS[path]) return SPECIAL_FIELD_LABELS[path];
  return resolveField(schema, path)?.title || humanizeKey(path);
}

function formatScalar(value: unknown): string {
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

/** Human-readable allowed-values string for a field. */
function describeAllowedValues(field: JsonSchemaField): string {
  if (Array.isArray(field.enum) && field.enum.length) {
    return field.enum.map((v) => String(v)).join(", ");
  }
  if (field.type === "boolean") return "Yes / No";
  if (field.type === "integer" || field.type === "number") {
    const kind = field.type === "integer" ? "integer" : "number";
    const { minimum: min, maximum: max } = field;
    if (min != null && max != null) return `${kind} (${min}–${max})`;
    if (min != null) return `${kind} (≥ ${min})`;
    if (max != null) return `${kind} (≤ ${max})`;
    return kind;
  }
  return "text";
}

function describeDefault(field: JsonSchemaField): string {
  const d = field.default;
  if (d === undefined || d === null) return "—";
  if (typeof d === "string" && d.trim() === "") return "—";
  return formatScalar(d);
}

/** Describe one visibility condition, e.g. `Tree build = igphyml` or `CSR analysis is enabled`. */
export function describeCondition(schema: ParamSchema, condition: Condition): string {
  const parts = Object.entries(condition).map(([key, value]) => {
    const label = fieldLabel(schema, key);
    if (typeof value === "boolean") return `${label} is ${value ? "enabled" : "disabled"}`;
    if (Array.isArray(value)) return `${label} is one of ${value.map((v) => String(v)).join(", ")}`;
    return `${label} = ${String(value)}`;
  });
  return parts.join(" and ");
}

/** Human-readable visibility note for a field, or "" when always shown. */
function describeVisibility(schema: ParamSchema, rule: VisibilityRule | undefined): string {
  if (!rule) return "";
  if (rule.when) return `Shown when ${describeCondition(schema, rule.when)}`;
  if (rule.whenAll?.length) {
    return `Shown when ${rule.whenAll.map((c) => describeCondition(schema, c)).join(" and ")}`;
  }
  if (rule.whenAny?.length) {
    return `Shown when ${rule.whenAny.map((c) => describeCondition(schema, c)).join(" or ")}`;
  }
  return "";
}

function mappingFor(name: string, content: MethodContent): string {
  if (content.fieldMappings[name]) return content.fieldMappings[name];
  if (name === "doMapping" || name.startsWith("column_map.")) return "N/A (wrapper-specific)";
  return "";
}

// ---- Public builder ---------------------------------------------------------

export function buildMethodDocModel(method: LoadedMethod, content: MethodContent): MethodDocModel {
  const { paramSchema, uiHints } = method;
  const order = uiHints.order ?? Object.keys(paramSchema.properties ?? {});
  const required = new Set(paramSchema.required ?? []);
  const visibility = uiHints.visibility ?? {};

  // field path -> section id
  const sectionOf = new Map<string, string>();
  for (const section of uiHints.sections ?? []) {
    for (const f of section.fields) sectionOf.set(f, section.id);
  }

  const buildField = (name: string): DocField | null => {
    const schema = resolveField(paramSchema, name);
    if (!schema) return null;
    // Skip object containers (e.g. the column_map parent) and deprecated aliases.
    if (schema.properties || schema.deprecated) return null;
    return {
      name,
      label: schema.title || humanizeKey(name),
      description: schema.description,
      allowedValues: describeAllowedValues(schema),
      defaultValue: describeDefault(schema),
      mapsTo: mappingFor(name, content),
      visibleWhen: describeVisibility(paramSchema, visibility[name]),
      required: required.has(name),
    };
  };

  const fields = order.map(buildField).filter((f): f is DocField => f !== null);

  // Group into sections (in declared section order); leftovers go to "Other Options".
  const sections: DocSection[] = [];
  const orderedSections = [...(uiHints.sections ?? [])].sort((a, b) => a.order - b.order);
  const claimed = new Set<string>();
  for (const section of orderedSections) {
    const sectionFields = fields.filter((f) => sectionOf.get(f.name) === section.id);
    sectionFields.forEach((f) => claimed.add(f.name));
    if (sectionFields.length) {
      sections.push({ id: section.id, label: section.label, fields: sectionFields });
    }
  }
  const leftover = fields.filter((f) => !claimed.has(f.name));
  if (leftover.length) {
    sections.push({ id: "other", label: "Other Options", fields: leftover });
  }

  const mutuallyExclusive = (uiHints.validation?.mutuallyExclusive ?? []).map((rule) => {
    const labels = rule.fields.map((f) => fieldLabel(paramSchema, f));
    return rule.message ?? `${labels.join(" and ")} are mutually exclusive.`;
  });

  const conditionalRequired = (uiHints.validation?.requiredWhen ?? []).map((rule) => {
    const label = fieldLabel(paramSchema, rule.field);
    return rule.message ?? `${label} is required when ${describeCondition(paramSchema, rule.when)}.`;
  });

  return {
    id: method.id,
    name: method.name,
    acceptFormats: method.acceptFormats,
    sections,
    mutuallyExclusive,
    conditionalRequired,
  };
}
