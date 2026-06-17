import Link from "next/link";
import {
  ArrowRight,
  Columns3,
  FolderTree,
  LayoutGrid,
  MousePointerClick,
  Repeat,
  Server,
  Shuffle,
  GitCompare,
  UploadCloud,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { VALUE_PROPS } from "@/features/docs/content";

const ICONS: Record<string, typeof LayoutGrid> = {
  "unified-ui": LayoutGrid,
  "any-input": Shuffle,
  "column-mapping": Columns3,
  "upload-once": UploadCloud,
  "param-transfer": Repeat,
  "sequence-tracing": GitCompare,
  results: FolderTree,
  server: Server,
  "node-detail": MousePointerClick,
};

export function FeatureHighlights() {
  return (
    <section className="border-b">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="mx-auto max-w-2xl space-y-3 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Everything you get out of the box</h2>
          <p className="text-muted-foreground">
            Conveniences the raw command-line tools simply don&apos;t offer.
          </p>
        </div>
        <div className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {VALUE_PROPS.map((prop) => {
            const Icon = ICONS[prop.id] ?? LayoutGrid;
            return (
              <Card key={prop.id} className="flex h-full flex-col transition-colors hover:border-primary/30">
                <CardHeader>
                  <div className="flex items-center gap-2">
                    <div className="rounded-lg bg-primary/10 p-2 text-primary">
                      <Icon className="h-5 w-5" />
                    </div>
                    <CardTitle className="text-base">{prop.title}</CardTitle>
                  </div>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-between gap-3">
                  <p className="text-sm leading-relaxed text-muted-foreground">{prop.body}</p>
                  {prop.href && prop.linkLabel && (
                    <Link
                      href={prop.href}
                      className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
                    >
                      {prop.linkLabel}
                      <ArrowRight className="h-3.5 w-3.5" />
                    </Link>
                  )}
                </CardContent>
              </Card>
            );
          })}
        </div>
      </div>
    </section>
  );
}
