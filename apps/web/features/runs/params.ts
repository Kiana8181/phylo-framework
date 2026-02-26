import type { MethodSpec, RunParams } from "@phylo/contracts";

export type ContractFieldType =
  | "string"
  | "number"
  | "integer"
  | "boolean"
  | "array"
  | "object";

export type ContractField = {
  name: string;
  label: string;
  description?: string;
  type?: ContractFieldType;
  order: number;
  section?: string;
  unit?: string;
  enumValues?: string[];
  enumLabels?: Record<string, string>;
};

export type ContractSection = {
  id: string;
  label: string;
  order: number;
};

export type ContractSpec = {
  methodKey: string;
  methodLabel?: string;
  fields: ContractField[];
  sections: ContractSection[];
};

export type FormattedParamValue =
  | { kind: "text"; text: string }
  | { kind: "chips"; chips: string[] }
  | { kind: "json"; json: string };

export type ResolvedParam = {
  key: string;
  label: string;
  description?: string;
  section?: string;
  value: unknown;
  formatted: FormattedParamValue;
};

export type ResolvedRunParams = {
  known: ResolvedParam[];
  unknown: ResolvedParam[];
  setCount: number;
};

type UnknownRecord = Record<string, unknown>;

type SectionMap = {
  byField: Map<string, string>;
  sections: ContractSection[];
};

function asRecord(value: unknown): UnknownRecord | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as UnknownRecord;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item : String(item)))
    .filter((item) => item.trim().length > 0);
}

function pickString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value.trim();
    }
  }
  return undefined;
}

function normalizeFieldType(value: unknown): ContractFieldType | undefined {
  if (value === "string") return "string";
  if (value === "number") return "number";
  if (value === "integer") return "integer";
  if (value === "boolean") return "boolean";
  if (value === "array") return "array";
  if (value === "object") return "object";
  return undefined;
}

function toOrder(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function parseEnumLabels(fieldDef: UnknownRecord, enumValues: string[]): Record<string, string> | undefined {
  const labels: Record<string, string> = {};

  const enumNames = toStringArray(fieldDef.enumNames);
  if (enumNames.length && enumNames.length === enumValues.length) {
    enumValues.forEach((value, idx) => {
      labels[value] = enumNames[idx];
    });
  }

  const oneOf = Array.isArray(fieldDef.oneOf) ? fieldDef.oneOf : [];
  for (const option of oneOf) {
    const optionRec = asRecord(option);
    if (!optionRec) continue;
    const constValue = optionRec.const;
    const title = pickString(optionRec.title, optionRec.label);
    if (typeof constValue === "string" && title) {
      labels[constValue] = title;
    }
  }

  const explicitMap = asRecord(fieldDef["x-enum-labels"]);
  if (explicitMap) {
    for (const [key, value] of Object.entries(explicitMap)) {
      if (typeof value === "string" && value.trim()) labels[key] = value;
    }
  }

  return Object.keys(labels).length ? labels : undefined;
}

function parseSections(uiHints: unknown): SectionMap {
  const byField = new Map<string, string>();
  const sections: ContractSection[] = [];
  const hints = asRecord(uiHints);
  const rawSections = hints?.sections;

  if (Array.isArray(rawSections)) {
    rawSections.forEach((rawSection, idx) => {
      const sectionRec = asRecord(rawSection);
      if (!sectionRec) return;

      const sectionId = pickString(sectionRec.id, sectionRec.key, sectionRec.name, sectionRec.title);
      if (!sectionId) return;
      const label = pickString(sectionRec.label, sectionRec.title, sectionId) ?? sectionId;
      const fields = toStringArray(sectionRec.fields);
      fields.forEach((fieldName) => byField.set(fieldName, sectionId));
      sections.push({ id: sectionId, label, order: toOrder(sectionRec.order, idx) });
    });
  }

  if (!Array.isArray(rawSections)) {
    const sectionMap = asRecord(rawSections);
    if (sectionMap) {
      Object.entries(sectionMap).forEach(([sectionId, rawValue], idx) => {
        const sectionRec = asRecord(rawValue);
        const label =
          pickString(sectionRec?.label, sectionRec?.title, sectionRec?.name, sectionId) ?? sectionId;
        const fields = toStringArray(sectionRec?.fields);
        fields.forEach((fieldName) => byField.set(fieldName, sectionId));
        sections.push({ id: sectionId, label, order: toOrder(sectionRec?.order, idx) });
      });
    }
  }

  sections.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label, "en"));
  return { byField, sections };
}

export function isValueSet(value: unknown): boolean {
  if (value == null) return false;
  if (typeof value === "string") return value.trim().length > 0;
  if (Array.isArray(value)) return value.length > 0;
  const record = asRecord(value);
  if (record) return Object.keys(record).length > 0;
  return true;
}

function normalizeRunParams(input: Record<string, unknown> | undefined | null): RunParams {
  if (!input) return {};
  const out: RunParams = {};
  Object.entries(input).forEach(([key, value]) => {
    out[key] = value;
  });
  return out;
}

export function toContractSpec(methodKey: string, methodSpec?: MethodSpec | null): ContractSpec {
  if (!methodSpec) {
    return { methodKey, methodLabel: methodKey, fields: [], sections: [] };
  }

  const schemaRec = asRecord(methodSpec.paramSchema) ?? {};
  const properties = asRecord(schemaRec.properties) ?? {};
  const hints = asRecord(methodSpec.uiHints) ?? {};
  const orderList = toStringArray(hints.order);
  const { byField, sections } = parseSections(methodSpec.uiHints);

  const knownNames = new Set(Object.keys(properties));
  const orderedNames = [
    ...orderList.filter((name) => knownNames.has(name)),
    ...Object.keys(properties).filter((name) => !orderList.includes(name)),
  ];

  const fields: ContractField[] = orderedNames.map((name, index) => {
    const rawField = asRecord(properties[name]) ?? {};
    const enumValues = toStringArray(rawField.enum);
    const enumLabels = parseEnumLabels(rawField, enumValues);
    const sectionFromField = pickString(
      rawField.section,
      rawField["x-section"],
      rawField["ui:section"],
      asRecord(rawField["x-ui"])?.section
    );
    const fieldSection = sectionFromField ?? byField.get(name);
    const fallbackType = enumValues.length ? "string" : undefined;

    return {
      name,
      label: pickString(rawField.title, rawField.label, name) ?? name,
      description: pickString(rawField.description),
      type: normalizeFieldType(rawField.type) ?? fallbackType,
      order: index,
      section: fieldSection,
      unit: pickString(rawField.unit, rawField["x-unit"], rawField["ui:unit"]),
      enumValues: enumValues.length ? enumValues : undefined,
      enumLabels,
    };
  });

  return {
    methodKey,
    methodLabel: methodSpec.name,
    fields,
    sections,
  };
}

function formatArrayItem(item: unknown): string {
  if (item == null) return "null";
  if (typeof item === "boolean") return item ? "Yes" : "No";
  if (typeof item === "string" || typeof item === "number") return String(item);
  try {
    return JSON.stringify(item);
  } catch {
    return String(item);
  }
}

export function formatParamValue(field: ContractField | undefined, value: unknown): FormattedParamValue {
  if (typeof value === "boolean") {
    return { kind: "text", text: value ? "Yes" : "No" };
  }

  if (Array.isArray(value)) {
    return { kind: "chips", chips: value.map(formatArrayItem) };
  }

  if (value && typeof value === "object") {
    try {
      return { kind: "json", json: JSON.stringify(value, null, 2) };
    } catch {
      return { kind: "text", text: String(value) };
    }
  }

  if (typeof value === "number") {
    const base = String(value);
    return { kind: "text", text: field?.unit ? `${base} ${field.unit}` : base };
  }

  if (typeof value === "string") {
    const enumLabel = field?.enumLabels?.[value];
    if (enumLabel) {
      return { kind: "text", text: enumLabel };
    }
    return { kind: "text", text: value };
  }

  return { kind: "text", text: String(value) };
}

export function resolveRunParams(
  contractSpec: ContractSpec | undefined,
  runParams: Record<string, unknown> | undefined | null
): ResolvedRunParams {
  const normalizedParams = normalizeRunParams(runParams);
  const fields = contractSpec?.fields ?? [];
  const fieldByName = new Map(fields.map((field) => [field.name, field] as const));

  const known: ResolvedParam[] = [];
  fields.forEach((field) => {
    if (!Object.prototype.hasOwnProperty.call(normalizedParams, field.name)) return;
    const value = normalizedParams[field.name];
    if (!isValueSet(value)) return;
    known.push({
      key: field.name,
      label: field.label,
      description: field.description,
      section: field.section,
      value,
      formatted: formatParamValue(field, value),
    });
  });

  const unknown: ResolvedParam[] = Object.entries(normalizedParams)
    .filter(([key, value]) => !fieldByName.has(key) && isValueSet(value))
    .sort(([left], [right]) => left.localeCompare(right, "en"))
    .map(([key, value]) => ({
      key,
      label: key,
      value,
      formatted: formatParamValue(undefined, value),
    }));

  return {
    known,
    unknown,
    setCount: known.length + unknown.length,
  };
}

export function toCopyPayload(args: {
  methodKey: string;
  runId?: string;
  resolved: ResolvedRunParams;
}): string {
  const params: RunParams = {};
  [...args.resolved.known, ...args.resolved.unknown].forEach((item) => {
    params[item.key] = item.value;
  });
  const payload: Record<string, unknown> = {
    methodKey: args.methodKey,
    params,
  };
  if (args.runId) payload.runId = args.runId;
  return JSON.stringify(payload, null, 2);
}
