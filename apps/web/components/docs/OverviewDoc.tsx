import Link from "next/link";
import { ArrowRight, ArrowUpRight, GitBranch } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { getMethodContent } from "@/features/docs/content";
import { VALUE_PROPS } from "@/features/docs/content";
import { METHOD_IDS } from "@/features/docs/types";

export function OverviewDoc() {
  return (
    <article className="mx-auto w-full max-w-5xl space-y-12">
      {/* Intro */}
      <header className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Phylo Runner documentation</h1>
        <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground">
          Phylo Runner is a single, friendly home for four B-cell phylogenetics methods — Dowser,
          GCtree, BrepPhylo and ClonalTree. Upload your data once, configure a method through a guided
          form, and let runs execute on the server. This guide explains what the package gives you over
          the raw tools, then documents each method&apos;s inputs and form fields in detail.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/dashboard">
            <Button className="gap-2">
              Go to the dashboard
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
        </div>
      </header>

      <Separator />

      {/* Why use it */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Why use Phylo Runner?</h2>
          <p className="text-muted-foreground">
            The raw methods are powerful but hard to work with. Phylo Runner removes the friction.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {VALUE_PROPS.map((prop) => (
            <Card key={prop.id} className="flex h-full flex-col">
              <CardHeader>
                <CardTitle className="text-base">{prop.title}</CardTitle>
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
          ))}
        </div>
      </section>

      <Separator />

      {/* Methods */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Method documentation</h2>
          <p className="text-muted-foreground">
            Each method page covers its capabilities, the input types it accepts, every form field, and
            the conditional behaviour of the form.
          </p>
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          {METHOD_IDS.map((id) => {
            const content = getMethodContent(id);
            return (
              <Link key={id} href={`/documents/${id}`} className="group">
                <Card className="h-full transition-colors group-hover:border-primary/40">
                  <CardHeader>
                    <div className="flex items-center gap-2">
                      <div className="rounded-lg bg-primary/10 p-2 text-primary">
                        <GitBranch className="h-5 w-5" />
                      </div>
                      <CardTitle className="text-lg">{content.displayName}</CardTitle>
                      <ArrowUpRight className="ml-auto h-4 w-4 text-muted-foreground transition-colors group-hover:text-primary" />
                    </div>
                    <CardDescription>{content.tagline}</CardDescription>
                  </CardHeader>
                </Card>
              </Link>
            );
          })}
        </div>
      </section>
    </article>
  );
}
