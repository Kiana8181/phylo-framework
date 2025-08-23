"use client";

import { useEffect, useMemo } from "react";
import { useForm, Controller } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectTrigger,
  SelectContent,
  SelectItem,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

type JSONSchema = {
  type?: string;
  title?: string;
  description?: string;
  enum?: string[];
  default?: unknown;
  properties?: Record<string, JSONSchema>;
  required?: string[];
  uiHints?: { order?: string[] };
};

function zodFromJsonSchema(schema: JSONSchema) {
  const props = schema.properties ?? {};
  const required = new Set(schema.required ?? []);
  const shape: Record<string, z.ZodTypeAny> = {};

  for (const [key, def] of Object.entries(props)) {
    let zt: z.ZodTypeAny;

    if (def.enum && def.enum.length) {
      zt = z.enum(def.enum as [string, ...string[]]);
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
    if ("default" in def!) {
      out[k] = def!.default;
      continue;
    }
    if (def!.enum) {
      out[k] = undefined;
      continue;
    }
    if (def!.type === "boolean") {
      out[k] = false;
      continue;
    }
    if (def!.type === "number" || def!.type === "integer") {
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
}: {
  schema: JSONSchema;
  defaults?: Record<string, any>;
  onSubmit: (values: Record<string, any>) => void;
}) {
  const zodSchema = useMemo(() => zodFromJsonSchema(schema), [schema]);
  const formDefaults = useMemo(
    () => defaultsFromSchema(schema, defaults),
    [schema, defaults]
  );

  const { control, handleSubmit, reset } = useForm({
    resolver: zodResolver(zodSchema),
    defaultValues: formDefaults,
  });

  useEffect(() => {
    reset(defaultsFromSchema(schema, defaults));
  }, [schema, defaults, reset]);

  const props = schema.properties ?? {};
  const order = schema.uiHints?.order ?? Object.keys(props);

  return (
    <form
      onSubmit={handleSubmit((data) => onSubmit(data))}
      className="space-y-4"
    >
      {order.map((name: string) => {
        const def = props[name]!;
        const type = def.enum ? "enum" : def.type;

        return (
          <div key={name} className="grid gap-2">
            <Label>{def.title ?? name}</Label>

            <Controller
              name={name as any}
              control={control}
              defaultValue={formDefaults[name]}
              render={({ field }) => {
                if (type === "boolean") {
                  return (
                    <Switch
                      checked={Boolean(field.value)}
                      onCheckedChange={field.onChange}
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
                    />
                  );
                }

                if (type === "enum") {
                  return (
                    <Select
                      value={(field.value ?? undefined) as string | undefined}
                      onValueChange={field.onChange}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select" />
                      </SelectTrigger>
                      <SelectContent>
                        {(def.enum as string[]).map((v) => (
                          <SelectItem key={v} value={v}>
                            {v}
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
                  />
                );
              }}
            />

            {def.description && (
              <p className="text-xs text-muted-foreground">{def.description}</p>
            )}
          </div>
        );
      })}

      <Button type="submit">Run</Button>
    </form>
  );
}
