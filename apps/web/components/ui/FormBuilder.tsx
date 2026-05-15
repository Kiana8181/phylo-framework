"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import { zodResolver } from "@hookform/resolvers/zod";
import { Loader2 } from "lucide-react";
import { ReactNode, useEffect, useMemo } from "react";
import { Controller, useForm, useWatch } from "react-hook-form";
import { z } from "zod";

type JSONSchema = {
  type?: string;
  title?: string;
  description?: string;
  enum?: Array<string | number | boolean>;
  default?: unknown;
  properties?: Record<string, JSONSchema>;
  required?: string[];
  uiHints?: {
    order?: string[];
    placeholders?: Record<string, string>;
    visibility?: Record<
      string,
      {
        when?: Record<string, any>;
        whenAll?: Array<Record<string, any>>;
        whenAny?: Array<Record<string, any>>;
      }
    >;
  };
};

type EnumPrimitive = string | number | boolean;
type FormValues = Record<string, any>;

type LeafField = {
  path: string;
  def: JSONSchema;
};

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

function asObject(value: unknown): Record<string, any> | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  return value as Record<string, any>;
}

function getNestedValue(source: unknown, path: string): unknown {
  if (!path) return source;
  const tokens = path.split(".");
  let current: any = source;
  for (const token of tokens) {
    if (!current || typeof current !== "object" || Array.isArray(current)) {
      return undefined;
    }
    current = current[token];
  }
  return current;
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

function zodFromJsonSchema(schema: JSONSchema): z.ZodType<FormValues, FormValues> {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const [key, def] of Object.entries(props)) {
    let zt: z.ZodTypeAny;
    const nestedProps = def?.properties ?? {};
    const isObject = def?.type === "object" || Object.keys(nestedProps).length > 0;
    const enumValues = enumValuesFromSchema(def);

    if (isObject && Object.keys(nestedProps).length > 0) {
      zt = zodFromJsonSchema(def);
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
      zt = z.preprocess((v) => (v === "" || v == null ? undefined : Number(v)), z.number());
    } else if (def.type === "boolean") {
      zt = z.boolean();
    } else {
      zt = z.string();
    }

    if (!required.has(key)) zt = zt.optional();
    shape[key] = zt;
  }

  return z.object(shape) as z.ZodType<FormValues, FormValues>;
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

export default function FormBuilder({
  schema,
  onSubmit,
  defaults,
  footer,
  disabled: formDisabled = false,
}: {
  schema: JSONSchema;
  defaults?: FormValues;
  onSubmit: (values: FormValues) => void;
  footer?: ReactNode;
  disabled?: boolean;
}) {
  const zodSchema = useMemo(() => zodFromJsonSchema(schema), [schema]);
  const formDefaults = useMemo(() => defaultsFromSchema(schema, defaults), [schema, defaults]);
  const leafFields = useMemo(() => collectLeafFields(schema), [schema]);
  const fieldMap = useMemo(() => {
    const map = new Map<string, JSONSchema>();
    leafFields.forEach((item) => map.set(item.path, item.def));
    return map;
  }, [leafFields]);

  const { control, handleSubmit, reset, formState } = useForm<FormValues>({
    resolver: zodResolver(zodSchema),
    defaultValues: formDefaults,
  });

  const disabled = formState.isSubmitting || formDisabled;

  const values = useWatch({ control });
  const placeholders = useMemo(() => schema.uiHints?.placeholders ?? {}, [schema.uiHints?.placeholders]);
  const visibility = useMemo(() => schema.uiHints?.visibility ?? {}, [schema.uiHints?.visibility]);

  const order = useMemo(() => {
    const explicit = Array.isArray(schema.uiHints?.order) ? schema.uiHints?.order : [];
    const filteredExplicit = explicit?.filter((name) => fieldMap.has(name));
    const remaining = leafFields.map((item) => item.path).filter((name) => !filteredExplicit?.includes(name));
    return [...(filteredExplicit || []), ...remaining];
  }, [schema.uiHints?.order, fieldMap, leafFields]);

  const testWhen = (cond: Record<string, any>) =>
    Object.entries(cond).every(([k, expected]) => {
      const v = getNestedValue(values, k);
      return Array.isArray(expected) ? expected.includes(v) : v === expected;
    });

  function isFieldVisible(name: string): boolean {
    const vis = (visibility as any)?.[name];
    if (!vis) return true;
    if (vis.when && !testWhen(vis.when)) return false;
    if (vis.whenAll && !vis.whenAll.every((c: any) => testWhen(c))) return false;
    if (vis.whenAny && !vis.whenAny.some((c: any) => testWhen(c))) return false;
    return true;
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
    const enumValues = enumValuesFromSchema(def);

    return (
      <div key={name} className="grid gap-2">
        <Label>{def?.title ?? name}</Label>

        <Controller
          name={name as any}
          control={control}
          defaultValue={getNestedValue(formDefaults, name)}
          render={({ field }) => {
            if (type === "boolean") {
              return (
                <Switch checked={Boolean(field.value)} onCheckedChange={field.onChange} disabled={disabled} />
              );
            }
            if (type === "number" || type === "integer") {
              return (
                <Input
                  type="number"
                  value={field.value ?? ""}
                  onChange={(e) => {
                    const v = e.target.value;
                    field.onChange(v === "" ? undefined : Number(v));
                  }}
                  onBlur={field.onBlur}
                  name={field.name}
                  ref={field.ref}
                  placeholder={placeholder}
                  disabled={disabled}
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
                  <SelectTrigger className="w-full">
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
            return (
              <Input
                value={field.value ?? ""}
                onChange={field.onChange}
                onBlur={field.onBlur}
                name={field.name}
                ref={field.ref}
                placeholder={placeholder}
                disabled={disabled}
              />
            );
          }}
        />

        {def?.description && <p className="text-xs text-muted-foreground">{def.description}</p>}
      </div>
    );
  }

  function GroupBox({ controller }: { controller: string }) {
    const childrenInOrder = order.filter((n) => groupMap.get(controller)?.includes(n));
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

  const basicFields = order.filter((name) => !groupedChildren.has(name));

  return (
    <form
      onSubmit={handleSubmit((data) => onSubmit(data))}
      className={cn("grid gap-4 grid-cols-1 md:grid-cols-2 xl:grid-cols-3")}
    >
      {basicFields.map((name) => (isFieldVisible(name) ? renderField(name) : null))}

      {[...groupMap.keys()].map((controller) => (
        <GroupBox key={controller} controller={controller} />
      ))}
      {footer}
      <div className="col-span-full flex justify-end">
        <Button type="submit" disabled={disabled}>
          {formState.isSubmitting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
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
