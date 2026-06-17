import { Card } from "@/components/ui/card";

export type Metric = { label: string; value: string | number | null | undefined };

/** A responsive grid of metric cards. Items with null/undefined values are skipped. */
export default function MetricGrid({ metrics }: { metrics: Metric[] }) {
  const shown = metrics.filter((m) => m.value != null && m.value !== "");
  if (!shown.length) return null;
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {shown.map((m) => (
        <Card key={m.label} className="gap-1 p-4">
          <div className="text-xs text-muted-foreground">{m.label}</div>
          <div className="text-2xl font-semibold">{m.value}</div>
        </Card>
      ))}
    </div>
  );
}
