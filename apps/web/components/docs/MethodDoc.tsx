import { ArrowUpRight, CheckCircle2, Info } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { getMethodContent } from "@/features/docs/content";
import { getMethodDocModel } from "@/features/docs/loader";
import type { MethodId } from "@/features/docs/types";
import { FieldTable } from "./FieldTable";
import { RichText } from "./RichText";

export function MethodDoc({ id }: { id: MethodId }) {
  const content = getMethodContent(id);
  const model = getMethodDocModel(id);

  const hasConditional =
    (content.conditionalNotes?.length ?? 0) > 0 ||
    model.conditionalRequired.length > 0 ||
    model.mutuallyExclusive.length > 0;

  return (
    <article className="mx-auto w-full max-w-5xl space-y-10">
      {/* Header */}
      <header className="space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="space-y-1">
            <h1 className="text-3xl font-bold tracking-tight">{content.displayName}</h1>
            <p className="text-muted-foreground">{content.tagline}</p>
          </div>
          <a
            href={content.externalDocUrl}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-sm font-medium text-foreground transition-colors hover:bg-accent hover:text-accent-foreground"
          >
            {content.externalDocLabel}
            <ArrowUpRight className="h-4 w-4" />
          </a>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Accepts:</span>
          {model.acceptFormats.map((fmt) => (
            <Badge key={fmt} variant="secondary">
              {fmt}
            </Badge>
          ))}
        </div>
      </header>

      {/* Summary + capabilities */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">What it does</h2>
        {content.summary.map((para, i) => (
          <p key={i} className="leading-relaxed text-muted-foreground">
            {para}
          </p>
        ))}
        <ul className="grid gap-2 sm:grid-cols-2">
          {content.capabilities.map((cap) => (
            <li key={cap} className="flex items-start gap-2 text-sm text-muted-foreground">
              <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
              <span>{cap}</span>
            </li>
          ))}
        </ul>
      </section>

      <Separator />

      {/* Input types */}
      <section className="space-y-4">
        <h2 className="text-xl font-semibold tracking-tight">Accepted input types</h2>
        <div className="overflow-hidden rounded-lg border">
          <Table>
            <TableHeader>
              <TableRow className="bg-muted/50 hover:bg-muted/50">
                <TableHead className="min-w-[8rem]">Input type</TableHead>
                <TableHead>What the framework does with it</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {content.inputTypes.map((row) => (
                <TableRow key={row.type}>
                  <TableCell className="font-medium text-foreground">{row.type}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {row.handling}
                    {row.needsVerification && (
                      <Badge variant="warning" className="ml-2 align-middle">
                        ⚠ NEEDS VERIFICATION
                      </Badge>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      </section>

      {/* ZIP bundle format */}
      {content.zipBundle && (
        <>
          <Separator />
          <section className="space-y-4">
            <h2 className="text-xl font-semibold tracking-tight">ZIP bundle format</h2>
            {content.zipBundle.intro.map((para, i) => (
              <p key={i} className="leading-relaxed text-muted-foreground">
                {para}
              </p>
            ))}

            <div className="space-y-2">
              <h3 className="text-base font-semibold text-foreground">Archive layout</h3>
              <ul className="list-disc space-y-1.5 pl-5 text-sm text-muted-foreground">
                {content.zipBundle.layout.map((rule, i) => (
                  <li key={i}>{rule}</li>
                ))}
              </ul>
            </div>

            <div className="space-y-2">
              <h3 className="text-base font-semibold text-foreground">Example manifest.json</h3>
              <pre className="overflow-x-auto rounded-lg border bg-muted/50 p-4 text-xs leading-relaxed text-foreground">
                <code>{content.zipBundle.manifestExample}</code>
              </pre>
            </div>

            <div className="space-y-4">
              <h3 className="text-base font-semibold text-foreground">
                Scenarios &amp; their mandatory files
              </h3>
              <p className="text-sm text-muted-foreground">
                The manifest&apos;s <code className="rounded bg-muted px-1 py-0.5">scenario</code> must
                be one of these values. Each row lists the roles that <em>must</em> appear under{" "}
                <code className="rounded bg-muted px-1 py-0.5">files</code> for that scenario.
              </p>
              <div className="overflow-hidden rounded-lg border">
                <Table>
                  <TableHeader>
                    <TableRow className="bg-muted/50 hover:bg-muted/50">
                      <TableHead className="min-w-[14rem]">Scenario</TableHead>
                      <TableHead>Use it when</TableHead>
                      <TableHead className="min-w-[16rem]">Mandatory files</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {content.zipBundle.scenarios.map((sc) => (
                      <TableRow key={sc.scenario} className="align-top">
                        <TableCell className="font-mono text-xs font-medium text-foreground">
                          {sc.scenario}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{sc.when}</TableCell>
                        <TableCell className="text-muted-foreground">
                          <ul className="space-y-1.5">
                            {sc.required.map((r) => (
                              <li key={r.role}>
                                <code className="rounded bg-muted px-1 py-0.5 text-foreground">
                                  {r.role}
                                </code>{" "}
                                — {r.description}
                              </li>
                            ))}
                          </ul>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </div>

            {content.zipBundle.fileFormats && content.zipBundle.fileFormats.length > 0 && (
              <div className="space-y-2">
                <h3 className="text-base font-semibold text-foreground">
                  Optional files &amp; their formats
                </h3>
                <p className="text-sm text-muted-foreground">
                  These roles may be added to any scenario&apos;s{" "}
                  <code className="rounded bg-muted px-1 py-0.5">files</code> map. To apply isotype
                  annotation, include <code className="rounded bg-muted px-1 py-0.5">isotype_mapfile</code>{" "}
                  (and an idmap).
                </p>
                <ul className="space-y-1.5 pl-5 text-sm text-muted-foreground">
                  {content.zipBundle.fileFormats.map((f) => (
                    <li key={f.role} className="list-disc">
                      <code className="rounded bg-muted px-1 py-0.5 text-foreground">{f.role}</code> —{" "}
                      {f.description}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </>
      )}

      <Separator />

      {/* Form fields */}
      <section className="space-y-5">
        <div className="space-y-1">
          <h2 className="text-xl font-semibold tracking-tight">Form fields</h2>
          <p className="text-sm text-muted-foreground">
            Every field shown in this method&apos;s form, generated from the package&apos;s field
            definitions so it always matches the live form. The mapping column is filled only where a
            field corresponds clearly to a native method parameter.
          </p>
        </div>
        <div className="space-y-8">
          {model.sections.map((section) => (
            <FieldTable key={section.id} section={section} />
          ))}
        </div>
      </section>

      {/* Conditional behaviour */}
      {hasConditional && (
        <>
          <Separator />
          <section className="space-y-4">
            <h2 className="text-xl font-semibold tracking-tight">Conditional fields &amp; behaviour</h2>
            <Card>
              <CardHeader>
                <CardTitle className="flex items-center gap-2 text-base">
                  <Info className="h-4 w-4 text-primary" />
                  Fields that appear or change based on other inputs
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-4 text-sm text-muted-foreground">
                {content.conditionalNotes && content.conditionalNotes.length > 0 && (
                  <ul className="list-disc space-y-1.5 pl-5">
                    {content.conditionalNotes.map((note, i) => (
                      <li key={i}>
                        <RichText text={note} />
                      </li>
                    ))}
                  </ul>
                )}
                {model.conditionalRequired.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="font-medium text-foreground">Conditionally required</p>
                    <ul className="list-disc space-y-1.5 pl-5">
                      {model.conditionalRequired.map((note, i) => (
                        <li key={i}>{note}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {model.mutuallyExclusive.length > 0 && (
                  <div className="space-y-1.5">
                    <p className="font-medium text-foreground">Mutually exclusive</p>
                    <ul className="list-disc space-y-1.5 pl-5">
                      {model.mutuallyExclusive.map((note, i) => (
                        <li key={i}>{note}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </CardContent>
            </Card>
          </section>
        </>
      )}
    </article>
  );
}
