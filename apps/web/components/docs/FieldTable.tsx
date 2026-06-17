import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DocSection } from "@/features/docs/types";
import { RichText } from "./RichText";

const NEEDS_VERIFICATION = "⚠ NEEDS VERIFICATION";

function MapsToCell({ value }: { value: string }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  if (value.startsWith("N/A")) {
    return <span className="text-muted-foreground">{value}</span>;
  }
  if (value.includes("NEEDS VERIFICATION")) {
    return <Badge variant="warning">{NEEDS_VERIFICATION}</Badge>;
  }
  return (
    <span className="text-foreground">
      <RichText text={value} />
    </span>
  );
}

export function FieldTable({ section }: { section: DocSection }) {
  return (
    <div className="space-y-3">
      <h4 className="text-sm font-semibold tracking-tight text-foreground">{section.label}</h4>
      <div className="overflow-hidden rounded-lg border">
        <Table>
          <TableHeader>
            <TableRow className="bg-muted/50 hover:bg-muted/50">
              <TableHead className="min-w-[10rem]">Field</TableHead>
              <TableHead className="min-w-[16rem]">What it is / used for</TableHead>
              <TableHead className="min-w-[9rem]">Allowed values</TableHead>
              <TableHead className="min-w-[6rem]">Default</TableHead>
              <TableHead className="min-w-[14rem]">Maps to method parameter</TableHead>
              <TableHead className="min-w-[12rem]">Visible when</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {section.fields.map((field) => (
              <TableRow key={field.name}>
                <TableCell>
                  <div className="flex flex-col gap-1">
                    <span className="font-medium text-foreground">{field.label}</span>
                    <code className="w-fit rounded bg-muted px-1 py-0.5 font-mono text-[0.7rem] text-muted-foreground">
                      {field.name}
                    </code>
                    {field.required && (
                      <Badge variant="secondary" className="w-fit">
                        Required
                      </Badge>
                    )}
                  </div>
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {field.description ? <RichText text={field.description} /> : "—"}
                </TableCell>
                <TableCell className="text-muted-foreground">{field.allowedValues}</TableCell>
                <TableCell className="text-muted-foreground">{field.defaultValue}</TableCell>
                <TableCell className="text-sm">
                  <MapsToCell value={field.mapsTo} />
                </TableCell>
                <TableCell className="text-muted-foreground">
                  {field.visibleWhen || <span className="text-muted-foreground/70">Always</span>}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
