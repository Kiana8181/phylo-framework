"use client";
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

type Schema = any;

function zodFromJsonSchema(schema: Schema) {
  const props = schema.properties ?? {};
  const shape: Record<string, any> = {};
  for (const [key, def] of Object.entries<any>(props)) {
    let zt: any;
    if (def.enum) zt = z.enum(def.enum as [string, ...string[]]);
    else if (def.type === "number" || def.type === "integer") zt = z.number();
    else if (def.type === "boolean") zt = z.boolean();
    else zt = z.string();
    if (!(schema.required ?? []).includes(key)) zt = zt.optional();
    shape[key] = zt;
  }
  return z.object(shape);
}

export default function FormBuilder({
  schema,
  onSubmit,
  defaults,
}: {
  schema: Schema;
  defaults?: Record<string, any>;
  onSubmit: (values: Record<string, any>) => void;
}) {
  const zodSchema = zodFromJsonSchema(schema);
  const { control, handleSubmit } = useForm({
    resolver: zodResolver(zodSchema),
    defaultValues: defaults ?? {},
  });

  const props = schema.properties ?? {};
  const order = schema.uiHints?.order ?? Object.keys(props);

  return (
    <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
      {order.map((name: string) => {
        const def = props[name];
        const type = def.enum ? "enum" : def.type;
        return (
          <div key={name} className="grid gap-2">
            <Label>{def.title ?? name}</Label>
            <Controller
              name={name as any}
              control={control}
              render={({ field }) => {
                if (type === "boolean") {
                  return (
                    <Switch
                      checked={!!field.value}
                      onCheckedChange={field.onChange}
                    />
                  );
                }
                if (type === "number" || type === "integer") {
                  return <Input type="number" {...field} />;
                }
                if (type === "enum") {
                  return (
                    <Select
                      onValueChange={field.onChange}
                      defaultValue={field.value}
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
                return <Input {...field} />;
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
