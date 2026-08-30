import Link from "next/link";
import { Download } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import {
  SAMPLE_FILENAME,
  SAMPLE_HREF,
  SAMPLE_SEQUENCE_COUNT,
  SAMPLE_TREE_SRC,
  visibleParamEntries,
} from "@/features/docs/sample";
import { METHOD_IDS, type MethodId } from "@/features/docs/types";
import { TryItButton } from "./TryItButton";

function DownloadSampleButton({ variant }: { variant?: "outline" }) {
  return (
    <Button asChild variant={variant} className="gap-2">
      <a href={SAMPLE_HREF} download>
        <Download className="h-4 w-4" />
        Download test dataset (.tsv)
      </a>
    </Button>
  );
}

function ParamsTable({ id }: { id: MethodId }) {
  const rows = visibleParamEntries(id);
  return (
    <div className="overflow-hidden rounded-lg border">
      <Table>
        <TableHeader>
          <TableRow className="bg-muted/50 hover:bg-muted/50">
            <TableHead className="min-w-[14rem]">Parameter</TableHead>
            <TableHead>Value</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rows.map((row) => (
            <TableRow key={row.path} className="align-top">
              <TableCell>
                <div className="flex flex-col gap-1">
                  <span className="font-medium text-foreground">{row.label}</span>
                  <code className="w-fit rounded bg-muted px-1 py-0.5 font-mono text-[0.7rem] text-muted-foreground">
                    {row.path}
                  </code>
                </div>
              </TableCell>
              <TableCell className="text-muted-foreground">
                {row.long ? (
                  <div className="max-h-24 max-w-xl overflow-y-auto rounded bg-muted/50 p-2 font-mono text-[0.7rem] leading-relaxed break-all">
                    {row.value}
                  </div>
                ) : (
                  <span className="font-mono text-xs text-foreground">{row.value}</span>
                )}
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}

/** The method's own tree plot, scaled to fit rather than scrolled. */
function TreeFigure({ id, name }: { id: MethodId; name: string }) {
  return (
    <figure className="space-y-3">
      <div className="rounded-lg border bg-white p-4 sm:p-6">
        {/* eslint-disable-next-line @next/next/no-img-element -- static run artifact in /public */}
        <img
          src={SAMPLE_TREE_SRC[id]}
          alt={`Tree produced by ${name} for clone 3128`}
          className="mx-auto block h-auto w-full max-w-3xl"
        />
      </div>
      <figcaption className="text-sm text-muted-foreground">
        The tree {name} produced from this dataset with the parameters above — the plot as the
        method itself renders it. Your run will also show it in the interactive tree panel, where
        you can zoom, collapse clades and export.
      </figcaption>
    </figure>
  );
}

function MethodSection({ id }: { id: MethodId }) {
  const content = getMethodContent(id);
  const model = getMethodDocModel(id);

  return (
    <section className="space-y-6 scroll-mt-6" id={id}>
      <div className="space-y-2">
        <h2 className="text-2xl font-semibold tracking-tight">{content.displayName}</h2>
        <p className="text-muted-foreground">{content.tagline}</p>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs font-medium text-muted-foreground">Accepts:</span>
          {model.acceptFormats.map((fmt) => (
            <Badge key={fmt} variant="secondary">
              {fmt}
            </Badge>
          ))}
          <Link
            href={`/documents/${id}`}
            className="ml-1 text-sm font-medium text-primary hover:underline"
          >
            Full field reference
          </Link>
        </div>
      </div>

      <div className="flex flex-wrap items-start gap-3">
        <DownloadSampleButton variant="outline" />
        <TryItButton methodId={id} label={content.displayName} />
      </div>

      <div className="space-y-3">
        <h3 className="text-base font-semibold text-foreground">Parameters used</h3>
        <p className="text-sm text-muted-foreground">
          Exactly what was submitted to the form for this run. Fields left at a blank value —
          every column-mapping override, since mapping is off — are omitted. Clicking{" "}
          <em>Try {content.displayName} yourself</em> loads these into the form for you.
        </p>
        <ParamsTable id={id} />
      </div>

      <div className="space-y-3">
        <h3 className="text-base font-semibold text-foreground">Output tree</h3>
        <TreeFigure id={id} name={content.displayName} />
      </div>
    </section>
  );
}

export function TryItYourselfDoc() {
  return (
    <article className="mx-auto w-full max-w-5xl space-y-12">
      <header className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Try it yourself</h1>
        <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground">
          One real dataset, run through all four methods. For each method below you get the file,
          the exact parameters that produced the tree, the tree itself, and a button that loads
          the whole thing into the run wizard so you can reproduce it in a couple of clicks.
        </p>
      </header>

      <section className="space-y-4">
        <h2 className="text-2xl font-semibold tracking-tight">The dataset</h2>
        <p className="text-muted-foreground">
          <code className="rounded bg-muted px-1 py-0.5 font-mono text-sm">{SAMPLE_FILENAME}</code>{" "}
          is <strong>clone 3128 of the official Dowser test dataset</strong>, extracted as a
          standalone AIRR rearrangement table: {SAMPLE_SEQUENCE_COUNT} sequences, one clone.
        </p>
        <p className="text-muted-foreground">
          It holds a single clone because <strong>GCtree accepts only one clone per run</strong> —
          a limitation of GCtree itself, not of this framework. Keeping the file to one clone is
          what lets the <em>same</em> file go through all four methods, which is the prerequisite
          for comparing their trees side by side.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <DownloadSampleButton />
          <span className="text-sm text-muted-foreground">
            TSV · {SAMPLE_SEQUENCE_COUNT} sequences · one clone · runs on all four methods
          </span>
        </div>
        <p className="text-sm text-muted-foreground">
          Not using GCtree? Then a dataset with more than one clone is fine for the other three,
          as long as it carries the columns that method needs — see{" "}
          <Link href="/documents/data-requirements" className="text-primary hover:underline">
            Data requirements
          </Link>
          . Just remember that runs are only comparable side by side when they came from the same
          dataset.
        </p>
      </section>

      {METHOD_IDS.map((id) => (
        <div key={id} className="space-y-12">
          <Separator />
          <MethodSection id={id} />
        </div>
      ))}
    </article>
  );
}
