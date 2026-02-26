"use client";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
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

function enumValuesFromSchema(def: JSONSchema): EnumPrimitive[] {
  if (!Array.isArray(def.enum)) return [];
  return def.enum.filter(
    (value): value is EnumPrimitive =>
      typeof value === "string" || typeof value === "number" || typeof value === "boolean"
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

function zodFromJsonSchema(schema: JSONSchema) {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const [key, def] of Object.entries(props)) {
    let zt: z.ZodTypeAny;
    const enumValues = enumValuesFromSchema(def);

    if (enumValues.length) {
      const literalSchemas = enumValues.map((value) => z.literal(value));
      const enumSchema =
        literalSchemas.length === 1
          ? literalSchemas[0]
          : z.union(literalSchemas as [typeof literalSchemas[0], typeof literalSchemas[0], ...typeof literalSchemas]);
      zt = z.preprocess((value) => coerceEnumInput(value, enumValues), enumSchema);
    } else if (def.type === "number" || def.type === "integer") {
      zt = z.preprocess(
        (v) => (v === "" || v == null ? undefined : Number(v)),
        z.number()
      );
    } else if (def.type === "boolean") {
      zt = z.boolean();
    } else {
      zt = z.string();
    }

    if (!required.has(key)) zt = zt.optional();
    shape[key] = zt;
  }

  return z.object(shape);
}

function defaultsFromSchema(
  schema: JSONSchema,
  overrides?: Record<string, any>
) {
  const props = schema.properties ?? {};
  const out: Record<string, any> = {};

  for (const [k, def] of Object.entries(props)) {
    if (overrides && k in overrides) {
      out[k] = overrides[k];
      continue;
    }
    if ("default" in (def || {})) {
      out[k] = (def as any).default;
      continue;
    }
    if (def?.enum) {
      out[k] = undefined;
      continue;
    }
    if (def?.type === "boolean") {
      out[k] = false;
      continue;
    }
    if (def?.type === "number" || def?.type === "integer") {
      out[k] = undefined;
      continue;
    }
    out[k] = "";
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
  defaults?: Record<string, any>;
  onSubmit: (values: Record<string, any>) => void;
  footer?: ReactNode;
  disabled?: boolean;
}) {
  const zodSchema = useMemo(() => zodFromJsonSchema(schema), [schema]);
  const formDefaults = useMemo(
    () => defaultsFromSchema(schema, defaults),
    [schema, defaults]
  );

  const { control, handleSubmit, reset, formState } = useForm({
    resolver: zodResolver(zodSchema),
    defaultValues: formDefaults,
  });

  const disabled = formState.isSubmitting || formDisabled;

  const values = useWatch({ control });
  const props = schema.properties ?? {};
  const order = schema.uiHints?.order ?? Object.keys(props);
  const placeholders = schema.uiHints?.placeholders ?? {};
  const visibility = schema.uiHints?.visibility ?? {};

  // helper: evaluate a visibility condition against current values
  const testWhen = (cond: Record<string, any>) =>
    Object.entries(cond).every(([k, expected]) => {
      const v = (values as any)[k];
      return Array.isArray(expected) ? expected.includes(v) : v === expected;
    });

  function isFieldVisible(name: string): boolean {
    const vis = (visibility as any)?.[name];
    if (!vis) return true;
    if (vis.when && !testWhen(vis.when)) return false;
    if (vis.whenAll && !vis.whenAll.every((c: any) => testWhen(c)))
      return false;
    if (vis.whenAny && !vis.whenAny.some((c: any) => testWhen(c))) return false;

    return true;
  }

  const groupMap = useMemo(() => {
    const m = new Map<string, string[]>();
    Object.entries(visibility).forEach(([child, rule]) => {
      const keys = Object.keys(
        rule.when ?? rule.whenAll?.[0] ?? rule.whenAny?.[0] ?? {}
      );
      const controller = keys[0];
      if (controller) m.set(controller, [...(m.get(controller) || []), child]);
    });
    return m;
  }, [visibility]);

  const groupedChildren = new Set<string>([...groupMap.values()].flat());

  useEffect(() => {
    reset(defaultsFromSchema(schema, defaults));
  }, [schema, defaults, reset]);

  function renderField(name: string) {
    const def = props[name]!;
    const type = def?.enum ? "enum" : def?.type;
    const placeholder = placeholders[name];
    const enumValues = enumValuesFromSchema(def);

    return (
      <div key={name} className="grid gap-2">
        <Label>{def?.title ?? name}</Label>

        <Controller
          name={name as any}
          control={control}
          defaultValue={(formDefaults as any)[name]}
          render={({ field }) => {
            if (type === "boolean") {
              return (
                <Switch
                  checked={Boolean(field.value)}
                  onCheckedChange={field.onChange}
                  disabled={disabled}
                />
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

        {def?.description && (
          <p className="text-xs text-muted-foreground">{def.description}</p>
        )}
      </div>
    );
  }

  function GroupBox({ controller }: { controller: string }) {
    const childrenInOrder = order.filter((n) =>
      groupMap.get(controller)?.includes(n)
    );
    const visibleChildren = childrenInOrder.filter((n) => isFieldVisible(n));
    if (!visibleChildren.length) return null;

    const title = props[controller]?.title ?? controller;
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
      {basicFields.map((name) =>
        isFieldVisible(name) ? renderField(name) : null
      )}

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
