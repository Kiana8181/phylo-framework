"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { cn } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { Spinner } from "@/components/ui/loading";
import { ReactNode, useEffect, useMemo, useRef } from "react";
import { Controller, useForm, useWatch, type FieldErrors } from "react-hook-form";
import { z } from "zod";

type FieldWidget = "textarea";

type VisibilityRule = {
  when?: Record<string, unknown>;
  whenAll?: Array<Record<string, unknown>>;
  whenAny?: Array<Record<string, unknown>>;
};

type RequiredWhenRule = VisibilityRule & {
  field: string;
  message?: string;
};

type MutuallyExclusiveRule = {
  fields: string[];
  message?: string;
};

type FormValidation = {
  requiredWhen?: RequiredWhenRule[];
  mutuallyExclusive?: MutuallyExclusiveRule[];
};

type UiSection = {
  id?: string;
  key?: string;
  name?: string;
  title?: string;
  label?: string;
  order?: number | string;
  fields?: unknown;
};

type JSONSchema = {
  type?: string;
  title?: string;
  description?: string;
  enum?: Array<string | number | boolean>;
  default?: unknown;
  properties?: Record<string, JSONSchema>;
  required?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  uiHints?: {
    order?: string[];
    placeholders?: Record<string, string>;
    widgets?: Record<string, FieldWidget>;
    visibility?: Record<string, VisibilityRule>;
    validation?: FormValidation;
    sections?: unknown;
  };
};

type EnumPrimitive = string | number | boolean;
type FormValues = Record<string, unknown>;

type LeafField = {
  path: string;
  def: JSONSchema;
};

export type FormSectionGroup = {
  id: string;
  label: string;
  fields: string[];
};

const DEFAULT_SECTION_ID = "__parameters";
const DEFAULT_SECTION_LABEL = "Parameters";

function pickString(...values: unknown[]): string | undefined {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return undefined;
}

function toOrder(value: unknown, fallback: number): number {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function toStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => (typeof item === "string" ? item : String(item)))
    .filter((item) => item.trim().length > 0);
}

export function buildFormSectionGroups(
  uiHints: JSONSchema["uiHints"] | undefined,
  orderedFields: string[],
  fieldNames?: Iterable<string>,
): FormSectionGroup[] {
  const rawSections = uiHints?.sections;
  if (!rawSections) return [];

  const validFields = new Set(fieldNames ?? orderedFields);
  const normalizedOrder = orderedFields.filter((field) => validFields.has(field));
  const sections: Array<FormSectionGroup & { order: number }> = [];
  const sectionIds = new Set<string>();
  const byField = new Map<string, string>();

  const addSection = (
    rawSection: UiSection | Record<string, unknown>,
    fallbackId: string,
    fallbackOrder: number,
  ) => {
    const sectionId = pickString(
      rawSection.id,
      rawSection.key,
      rawSection.name,
      rawSection.title,
      fallbackId,
    );
    if (!sectionId || sectionIds.has(sectionId)) return;

    const label = pickString(rawSection.label, rawSection.title, rawSection.name, sectionId) ?? sectionId;
    const fields = toStringArray(rawSection.fields).filter((field) => validFields.has(field));
    fields.forEach((field) => byField.set(field, sectionId));
    sections.push({ id: sectionId, label, order: toOrder(rawSection.order, fallbackOrder), fields: [] });
    sectionIds.add(sectionId);
  };

  if (Array.isArray(rawSections)) {
    rawSections.forEach((rawSection, idx) => {
      const sectionRec = asObject(rawSection);
      if (sectionRec) addSection(sectionRec, `section-${idx}`, idx);
    });
  } else {
    const sectionMap = asObject(rawSections);
    if (sectionMap) {
      Object.entries(sectionMap).forEach(([sectionId, rawValue], idx) => {
        const sectionRec = asObject(rawValue) ?? {};
        addSection({ ...sectionRec, id: sectionId }, sectionId, idx);
      });
    }
  }

  sections.sort((a, b) => a.order - b.order || a.label.localeCompare(b.label, "en"));
  const groupsById = new Map(sections.map((section) => [section.id, section]));

  for (const field of normalizedOrder) {
    const sectionId = byField.get(field);
    if (!sectionId) continue;
    groupsById.get(sectionId)?.fields.push(field);
  }

  const fallbackFields = normalizedOrder.filter((field) => !byField.has(field));
  const groups = sections.filter((section) => section.fields.length > 0);
  if (fallbackFields.length > 0) {
    groups.push({
      id: DEFAULT_SECTION_ID,
      label: DEFAULT_SECTION_LABEL,
      order: Number.MAX_SAFE_INTEGER,
      fields: fallbackFields,
    });
  }

  return groups.map(({ id, label, fields }) => ({ id, label, fields }));
}

function enumValuesFromSchema(def: JSONSchema): EnumPrimitive[] {
  if (!Array.isArray(def.enum)) return [];
  return def.enum.filter(
    (value): value is EnumPrimitive =>
      typeof value === "string" || typeof value === "number" || typeof value === "boolean",
  );
}

function enumToken(value: EnumPrimitive): string {
  return `${typeof value}:${String(value)}`;
}

function enumFromToken(token: string, values: EnumPrimitive[]): EnumPrimitive | undefined {
  return values.find((value) => enumToken(value) === token);
}

function coerceEnumInput(value: unknown, values: EnumPrimitive[]): unknown {
  if (value == null) return value;
  if (values.some((candidate) => candidate === value)) return value;
  if (typeof value !== "string") return value;

  const fromToken = enumFromToken(value, values);
  if (fromToken !== undefined) return fromToken;

  const hasNumber = values.some((candidate) => typeof candidate === "number");
  if (hasNumber && value.trim() !== "") {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) {
      const match = values.find((candidate) => typeof candidate === "number" && candidate === numeric);
      if (match !== undefined) return match;
    }
  }

  const hasBoolean = values.some((candidate) => typeof candidate === "boolean");
  if (hasBoolean) {
    const lowered = value.trim().toLowerCase();
    if (lowered === "true" || lowered === "false") {
      const boolValue = lowered === "true";
      const match = values.find((candidate) => typeof candidate === "boolean" && candidate === boolValue);
      if (match !== undefined) return match;
    }
  }

  const stringMatch = values.find((candidate) => typeof candidate === "string" && candidate === value);
  if (stringMatch !== undefined) return stringMatch;

  return value;
}

function asObject(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function getNestedValue(source: unknown, path: string): unknown {
  if (!path) return source;
  const tokens = path.split(".");
  let current: unknown = source;
  for (const token of tokens) {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    current = (current as Record<string, unknown>)[token];
  }
  return current;
}

function matchesCondition(values: unknown, cond: Record<string, unknown>): boolean {
  return Object.entries(cond).every(([key, expected]) => {
    const actual = getNestedValue(values, key);
    return Array.isArray(expected) ? expected.includes(actual) : actual === expected;
  });
}

function matchesRule(values: unknown, rule: VisibilityRule): boolean {
  if (rule.when && !matchesCondition(values, rule.when)) return false;
  if (rule.whenAll && !rule.whenAll.every((c) => matchesCondition(values, c))) return false;
  if (rule.whenAny && !rule.whenAny.some((c) => matchesCondition(values, c))) return false;
  return true;
}

function isEmptyValue(value: unknown): boolean {
  return value == null || (typeof value === "string" && value.trim() === "");
}

function collectLeafFields(schema: JSONSchema, prefix = ""): LeafField[] {
  const props = schema.properties ?? {};
  const out: LeafField[] = [];

  for (const [key, def] of Object.entries(props)) {
    const path = prefix ? `${prefix}.${key}` : key;
    const nestedProps = def?.properties ?? {};
    const isObject = def?.type === "object" || Object.keys(nestedProps).length > 0;
    if (isObject && Object.keys(nestedProps).length > 0) {
      out.push(...collectLeafFields(def, path));
      continue;
    }
    out.push({ path, def });
  }
  return out;
}

function zodObjectFromJsonSchema(schema: JSONSchema): z.ZodTypeAny {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const [key, def] of Object.entries(props)) {
    let zt: z.ZodTypeAny;
    const nestedProps = def?.properties ?? {};
    const isObject = def?.type === "object" || Object.keys(nestedProps).length > 0;
    const enumValues = enumValuesFromSchema(def);

    if (isObject && Object.keys(nestedProps).length > 0) {
      zt = zodObjectFromJsonSchema(def);
    } else if (enumValues.length) {
      const literalSchemas = enumValues.map((value) => z.literal(value));
      const enumSchema =
        literalSchemas.length === 1
          ? literalSchemas[0]
          : z.union(
              literalSchemas as [
                (typeof literalSchemas)[0],
                (typeof literalSchemas)[0],
                ...typeof literalSchemas,
              ],
            );
      zt = z.preprocess((value) => coerceEnumInput(value, enumValues), enumSchema);
    } else if (def.type === "number" || def.type === "integer") {
      let num = z.number();
      if (def.type === "integer") num = num.int();
      if (typeof def.minimum === "number") num = num.min(def.minimum);
      if (typeof def.maximum === "number") num = num.max(def.maximum);
      zt = z.preprocess((v) => (v === "" || v == null ? undefined : Number(v)), num);
    } else if (def.type === "boolean") {
      zt = z.boolean();
    } else {
      let str = z.string();
      if (typeof def.minLength === "number") str = str.min(def.minLength);
      if (typeof def.maxLength === "number") str = str.max(def.maxLength);
      if (typeof def.pattern === "string") str = str.regex(new RegExp(def.pattern));
      zt = str;
    }

    if (!required.has(key)) zt = zt.optional();
    shape[key] = zt;
  }

  return z.object(shape);
}

export function buildZodSchema(schema: JSONSchema): z.ZodType<FormValues, FormValues> {
  const base = zodObjectFromJsonSchema(schema);
  const validation = schema.uiHints?.validation;
  if (!validation?.requiredWhen?.length && !validation?.mutuallyExclusive?.length) {
    return base as z.ZodType<FormValues, FormValues>;
  }

  return base.superRefine((data: unknown, ctx: z.RefinementCtx) => {
    for (const rule of validation.requiredWhen ?? []) {
      if (matchesRule(data, rule) && isEmptyValue(getNestedValue(data, rule.field))) {
        ctx.addIssue({
          code: "custom",
          path: rule.field.split("."),
          message: rule.message ?? "This field is required.",
        });
      }
    }
    for (const rule of validation.mutuallyExclusive ?? []) {
      const set = rule.fields.filter((field) => !isEmptyValue(getNestedValue(data, field)));
      if (set.length > 1) {
        for (const field of set) {
          ctx.addIssue({
            code: "custom",
            path: field.split("."),
            message: rule.message ?? "These fields are mutually exclusive.",
          });
        }
      }
    }
  }) as z.ZodType<FormValues, FormValues>;
}

function defaultForField(def: JSONSchema, hasOverride: boolean, overrideValue: unknown): unknown {
  const nestedProps = def?.properties ?? {};
  const isObject = def?.type === "object" || Object.keys(nestedProps).length > 0;

  if (isObject && Object.keys(nestedProps).length > 0) {
    const nestedOverride = asObject(overrideValue) ?? undefined;
    return defaultsFromSchema(def, nestedOverride);
  }

  if (hasOverride) return overrideValue;
  if ("default" in (def || {})) return (def as any).default;
  if (def?.enum) return undefined;
  if (def?.type === "boolean") return false;
  if (def?.type === "number" || def?.type === "integer") return undefined;
  return "";
}

function defaultsFromSchema(schema: JSONSchema, overrides?: Record<string, any>) {
  const props = schema.properties ?? {};
  const out: Record<string, any> = {};

  for (const [k, def] of Object.entries(props)) {
    const hasOverride = Boolean(overrides && Object.prototype.hasOwnProperty.call(overrides, k));
    const overrideValue = hasOverride ? overrides?.[k] : undefined;
    out[k] = defaultForField(def, hasOverride, overrideValue);
  }

  return out;
}

function GroupBox({
  controller,
  childrenInOrder,
  fieldMap,
  isFieldVisible,
  renderField,
}: {
  controller: string;
  childrenInOrder: string[];
  fieldMap: Map<string, JSONSchema>;
  isFieldVisible: (name: string) => boolean;
  renderField: (name: string) => ReactNode;
}) {
  const visibleChildren = childrenInOrder.filter((n) => isFieldVisible(n));
  if (!visibleChildren.length) return null;

  const title = fieldMap.get(controller)?.title ?? controller;
  return (
    <div className="col-span-full rounded-2xl border bg-card/30">
      <div className="flex items-center justify-between px-4 py-2 border-b">
        <div className="text-sm font-medium">{title}</div>
        <div className="text-xs text-muted-foreground">Advanced</div>
      </div>
      <div className="p-4 grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
        {visibleChildren.map((name) => renderField(name))}
      </div>
    </div>
  );
}

export default function FormBuilder({
  schema,
  onSubmit,
  defaults,
  footer,
  disabled: formDisabled = false,
  context,
}: {
  schema: JSONSchema;
  defaults?: FormValues;
  onSubmit: (values: FormValues) => void | Promise<void>;
  footer?: ReactNode;
  disabled?: boolean;
  /** Extra read-only values (e.g. `$inputFormat`) merged in for visibility
   *  evaluation only. Never submitted. Use `$`-prefixed reserved keys. */
  context?: Record<string, unknown>;
}) {
  const zodSchema = useMemo(() => buildZodSchema(schema), [schema]);
  const formDefaults = useMemo(() => defaultsFromSchema(schema, defaults), [schema, defaults]);
  const leafFields = useMemo(() => collectLeafFields(schema), [schema]);
  const fieldMap = useMemo(() => {
    const map = new Map<string, JSONSchema>();
    leafFields.forEach((item) => map.set(item.path, item.def));
    return map;
  }, [leafFields]);

  const formRef = useRef<HTMLFormElement>(null);
  const { control, handleSubmit, reset, formState } = useForm<FormValues>({
    resolver: zodResolver(zodSchema),
    defaultValues: formDefaults,
    mode: "onTouched",
    reValidateMode: "onChange",
    shouldFocusError: false,
  });

  const disabled = formState.isSubmitting || formDisabled;

  const values = useWatch({ control });
  // Values used to evaluate visibility rules: live form values plus any
  // read-only context (e.g. `$inputFormat`). Context is never submitted.
  const evalValues = useMemo(() => ({ ...context, ...values }), [context, values]);
  const placeholders = useMemo(() => schema.uiHints?.placeholders ?? {}, [schema.uiHints?.placeholders]);
  const widgets = useMemo(() => schema.uiHints?.widgets ?? {}, [schema.uiHints?.widgets]);
  const visibility = useMemo(() => schema.uiHints?.visibility ?? {}, [schema.uiHints?.visibility]);

  const order = useMemo(() => {
    const explicit = Array.isArray(schema.uiHints?.order) ? schema.uiHints?.order : [];
    const filteredExplicit = explicit?.filter((name) => fieldMap.has(name));
    const remaining = leafFields.map((item) => item.path).filter((name) => !filteredExplicit?.includes(name));
    return [...(filteredExplicit || []), ...remaining];
  }, [schema.uiHints?.order, fieldMap, leafFields]);

  const sectionGroups = useMemo(
    () => buildFormSectionGroups(schema.uiHints, order, fieldMap.keys()),
    [schema.uiHints, order, fieldMap],
  );

  function isFieldVisible(name: string): boolean {
    const vis = visibility[name];
    if (!vis) return true;
    return matchesRule(evalValues, vis);
  }

  function filterVisibleValues(data: FormValues): FormValues {
    const out: FormValues = {};
    for (const [key, value] of Object.entries(data)) {
      if (isFieldVisible(key)) out[key] = value;
    }
    return out;
  }

  function scrollToFirstError(errors: FieldErrors<FormValues>) {
    const firstName = order.find((name) => Boolean(getNestedValue(errors, name)));
    if (!firstName) return;
    const wrapper = formRef.current?.querySelector<HTMLElement>(`[data-field="${firstName}"]`);
    if (!wrapper) return;
    wrapper.scrollIntoView({ behavior: "smooth", block: "center" });
    wrapper
      .querySelector<HTMLElement>("input, textarea, [role='combobox'], button")
      ?.focus({ preventScroll: true });
  }

  const groupMap = useMemo(() => {
    const m = new Map<string, string[]>();
    Object.entries(visibility).forEach(([child, rule]) => {
      if (!fieldMap.has(child)) return;
      const firstCond =
        rule.when ??
        (Array.isArray(rule.whenAll) && rule.whenAll.length > 0 ? rule.whenAll[0] : undefined) ??
        (Array.isArray(rule.whenAny) && rule.whenAny.length > 0 ? rule.whenAny[0] : undefined) ??
        {};
      const keys = Object.keys(firstCond);
      const controller = keys[0];
      if (controller && fieldMap.has(controller)) {
        m.set(controller, [...(m.get(controller) || []), child]);
      }
    });
    return m;
  }, [visibility, fieldMap]);

  const groupedChildren = new Set<string>([...groupMap.values()].flat());

  useEffect(() => {
    reset(defaultsFromSchema(schema, defaults));
  }, [schema, defaults, reset]);

  function renderField(name: string) {
    const def = fieldMap.get(name);
    if (!def) return null;

    const type = def?.enum ? "enum" : def?.type;
    const placeholder = placeholders[name];
    const widget = widgets[name];
    const enumValues = enumValuesFromSchema(def);

    return (
      <div key={name} data-field={name} className="grid gap-2">
        <Label>{def?.title ?? name}</Label>

        <Controller
          name={name}
          control={control}
          defaultValue={getNestedValue(formDefaults, name)}
          render={({ field, fieldState }) => {
            const control = (() => {
            if (type === "boolean") {
              return (
                <Switch checked={Boolean(field.value)} onCheckedChange={field.onChange} disabled={disabled} />
              );
            }
            if (type === "number" || type === "integer") {
              const numberInputValue =
                field.value === undefined || field.value === null
                  ? ""
                  : typeof field.value === "number" || typeof field.value === "string"
                    ? field.value
                    : "";
              return (
                <Input
                  type="number"
                  value={numberInputValue}
                  onChange={(e) => {
                    const v = e.target.value;
                    field.onChange(v === "" ? undefined : Number(v));
                  }}
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                  placeholder={placeholder}
                  disabled={disabled}
                  aria-invalid={!!fieldState.error}
                />
              );
            }
            if (type === "enum") {
              const selected =
                enumValues.find((value) => value === field.value) !== undefined
                  ? enumToken(field.value as EnumPrimitive)
                  : undefined;
              return (
                <Select
                  value={selected}
                  onValueChange={(token) => {
                    const parsed = enumFromToken(token, enumValues);
                    field.onChange(parsed ?? token);
                  }}
                  disabled={disabled}
                >
                  <SelectTrigger className="w-full" aria-invalid={!!fieldState.error}>
                    <SelectValue placeholder="Select" />
                  </SelectTrigger>
                  <SelectContent>
                    {enumValues.map((value) => (
                      <SelectItem key={enumToken(value)} value={enumToken(value)}>
                        {String(value)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              );
            }
            if (widget === "textarea") {
              return (
                <Textarea
                  value={String(field.value ?? "")}
                  onChange={field.onChange}
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                  placeholder={placeholder}
                  disabled={disabled}
                  rows={2}
                  className="font-mono text-xs"
                  aria-invalid={!!fieldState.error}
                />
              );
            }
            return (
              <Input
                value={String(field.value ?? "")}
                onChange={field.onChange}
                onBlur={field.onBlur}
                name={field.name}
                ref={field.ref}
                placeholder={placeholder}
                disabled={disabled}
                aria-invalid={!!fieldState.error}
              />
            );
            })();
            return (
              <>
                {control}
                {fieldState.error ? (
                  <p className="text-destructive text-sm">{String(fieldState.error.message ?? "")}</p>
                ) : null}
              </>
            );
          }}
        />

        {def?.description && <p className="text-xs text-muted-foreground">{def.description}</p>}
      </div>
    );
  }

  const basicFields = order.filter((name) => !groupedChildren.has(name));
  const hasSections = sectionGroups.length > 0;

  function renderFieldsWithGroups(fields: string[]) {
    const fieldSet = new Set(fields);
    const controllers = [...groupMap.keys()].filter((controller) => {
      const children = groupMap.get(controller) ?? [];
      return children.some((child) => fieldSet.has(child));
    });

    return (
      <>
        {fields
          .filter((name) => !groupedChildren.has(name))
          .map((name) => (isFieldVisible(name) ? renderField(name) : null))}

        {controllers.map((controller) => {
          const childrenInOrder = fields.filter((name) => groupMap.get(controller)?.includes(name));
          return (
            <GroupBox
              key={controller}
              controller={controller}
              childrenInOrder={childrenInOrder}
              fieldMap={fieldMap}
              isFieldVisible={isFieldVisible}
              renderField={renderField}
            />
          );
        })}
      </>
    );
  }

  function hasVisibleFieldsWithGroups(fields: string[]) {
    const fieldSet = new Set(fields);
    const visibleBasic = fields.some((name) => !groupedChildren.has(name) && isFieldVisible(name));
    const visibleGrouped = [...groupMap.values()]
      .flat()
      .some((name) => fieldSet.has(name) && isFieldVisible(name));

    return visibleBasic || visibleGrouped;
  }

  function renderSection(group: FormSectionGroup) {
    if (!hasVisibleFieldsWithGroups(group.fields)) return null;

    return (
      <section key={group.id} className="col-span-full rounded-lg border bg-card/30">
        <div className="border-b px-4 py-3">
          <h4 className="text-sm font-semibold">{group.label}</h4>
        </div>
        <div className="grid grid-cols-1 gap-4 p-4 md:grid-cols-2 xl:grid-cols-3">
          {renderFieldsWithGroups(group.fields)}
        </div>
      </section>
    );
  }

  return (
    <form
      ref={formRef}
      onSubmit={handleSubmit(
        async (data) => {
          await onSubmit(filterVisibleValues(data));
        },
        (errors) => scrollToFirstError(errors),
      )}
      className={cn("grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3")}
    >
      {hasSections ? (
        sectionGroups.map((group) => renderSection(group))
      ) : (
        <>
          {basicFields.map((name) => (isFieldVisible(name) ? renderField(name) : null))}

          {[...groupMap.keys()].map((controller) => (
            <GroupBox
              key={controller}
              controller={controller}
              childrenInOrder={order.filter((n) => groupMap.get(controller)?.includes(n))}
              fieldMap={fieldMap}
              isFieldVisible={isFieldVisible}
              renderField={renderField}
            />
          ))}
        </>
      )}
      {footer}
      <div className="col-span-full flex justify-end">
        <Button type="submit" disabled={disabled}>
          {formState.isSubmitting ? (
            <>
              <Spinner className="mr-2" />
              Running…
            </>
          ) : (
            "Run"
          )}
        </Button>
      </div>
    </form>
  );
}
