import { Card } from "@/components/ui/card";
import type { MethodInfo } from "@phylo/contracts";

export default function MethodCard({
  m,
  active,
  onClick,
}: {
  m: MethodInfo;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <Card
      className={`p-4 cursor-pointer border transition-colors ${
        active ? "ring-2 ring-primary border-primary/30" : ""
      }`}
      onClick={onClick}
    >
      <div className="font-medium">{m.name}</div>
      <div className="text-xs text-muted-foreground">v{m.version}</div>
    </Card>
  );
}
