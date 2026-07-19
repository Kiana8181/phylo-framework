import Link from "next/link";
import { ArrowRight, Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import {
  buildCompatibilityModel,
  getUniversalColumns,
  type ColumnStatus,
} from "@/features/docs/compatibility";
import { getMethodDocModel } from "@/features/docs/loader";
import { getMethodContent } from "@/features/docs/content";
import { METHOD_IDS } from "@/features/docs/types";

const SAMPLE_HREF = "/samples/phylo-runner-sample.tsv";

function StatusCell({ status }: { status: ColumnStatus }) {
  switch (status) {
    case "required":
      return <Badge variant="default">Required</Badge>;
    case "optional":
      return <Badge variant="secondary">Optional</Badge>;
    case "conditional":
      return <Badge variant="outline">Conditional</Badge>;
    case "not-used":
      return (
        <span className="text-muted-foreground" aria-label="Not used">
          —
        </span>
      );
  }
}

export function DataRequirementsDoc() {
  const model = buildCompatibilityModel();
  const universal = getUniversalColumns();
  const labelFor = new Map(model.map((row) => [row.column, row.label]));
  const methods = METHOD_IDS.map((id) => ({
    id,
    name: getMethodContent(id).displayName,
    formats: getMethodDocModel(id).acceptFormats,
  }));

  return (
    <article className="mx-auto w-full max-w-5xl space-y-12">
      {/* Intro */}
      <header className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Data requirements</h1>
        <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground">
          Each method expects its own set of input columns. This page answers one question directly: which
          columns does your dataset need so you can run — and compare — every method on the same file? The
          tables below are generated from the same contracts the uploader validates against, so they never
          drift from what the app actually requires.
        </p>
      </header>

      <Separator />

      {/* Universal columns — the direct answer */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Universal columns</h2>
          <p className="text-muted-foreground">
            These columns are accepted by <strong>every</strong> method. A dataset that contains them can be
            run through all four and compared side by side. (Derived as the intersection of every
            method&apos;s accepted columns.)
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {universal.map((column) => (
            <Badge key={column} variant="secondary" className="font-mono text-sm">
              {column}
            </Badge>
          ))}
        </div>
        <p className="text-sm text-muted-foreground">
          {universal.map((c) => labelFor.get(c) ?? c).join(" · ")}
        </p>
      </section>

      <Separator />

      {/* Full matrix */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Full column matrix</h2>
          <p className="text-muted-foreground">
            Every column any method can use, and how each method treats it. Columns marked{" "}
            <em>conditional</em> are only needed when a particular option is enabled (noted inline).
          </p>
        </div>

        {/* Legend */}
        <div className="flex flex-wrap items-center gap-3 text-sm">
          <span className="inline-flex items-center gap-1.5">
            <Badge variant="default">Required</Badge> must be present
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Badge variant="secondary">Optional</Badge> used if present
          </span>
          <span className="inline-flex items-center gap-1.5">
            <Badge variant="outline">Conditional</Badge> needed for some options
          </span>
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">— not used</span>
        </div>

        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th className="px-3 py-2 font-semibold">Column</th>
                {methods.map((m) => (
                  <th key={m.id} className="px-3 py-2 font-semibold whitespace-nowrap">
                    {m.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {model.map((row) => (
                <tr key={row.column} className="border-b last:border-b-0 align-top">
                  <td className="px-3 py-2">
                    <div className="font-mono text-xs sm:text-sm">{row.column}</div>
                    {row.conditionNote && (
                      <div className="mt-0.5 text-xs text-muted-foreground">{row.conditionNote}</div>
                    )}
                  </td>
                  {METHOD_IDS.map((id) => (
                    <td key={id} className="px-3 py-2">
                      <StatusCell status={row.byMethod[id]} />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Separator />

      {/* Format compatibility */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">File-format compatibility</h2>
          <p className="text-muted-foreground">
            Having the right columns is only half the story — the file must also be in a format the method
            accepts. To compare across methods, upload a format every target method accepts.
          </p>
        </div>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr className="border-b bg-muted/40 text-left">
                <th className="px-3 py-2 font-semibold">Method</th>
                <th className="px-3 py-2 font-semibold">Accepted formats</th>
              </tr>
            </thead>
            <tbody>
              {methods.map((m) => (
                <tr key={m.id} className="border-b last:border-b-0">
                  <td className="px-3 py-2 font-medium whitespace-nowrap">{m.name}</td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap gap-1.5">
                      {m.formats.length ? (
                        m.formats.map((fmt) => (
                          <Badge key={fmt} variant="secondary">
                            {fmt}
                          </Badge>
                        ))
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Separator />

      {/* Sample dataset */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Sample dataset</h2>
          <p className="text-muted-foreground">
            A ready-to-fill template whose header row is every column the four methods require between them
            (in canonical AIRR names). Fill in your rows and the same file runs through all four methods with
            their default settings — no per-method reshaping.
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          <Button asChild className="gap-2">
            <a href={SAMPLE_HREF} download>
              <Download className="h-4 w-4" />
              Download template (.tsv)
            </a>
          </Button>
          <span className="text-sm text-muted-foreground">
            TSV · required headers for all four methods · empty rows
          </span>
        </div>

        <p className="text-sm text-muted-foreground">
          Once uploaded, map each method&apos;s expected inputs on the run form, or read a specific
          method&apos;s field reference below.
        </p>
        <div className="flex flex-wrap gap-3">
          {METHOD_IDS.map((id) => (
            <Link
              key={id}
              href={`/documents/${id}`}
              className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
            >
              {getMethodContent(id).displayName}
              <ArrowRight className="h-3.5 w-3.5" />
            </Link>
          ))}
        </div>
      </section>
    </article>
  );
}
