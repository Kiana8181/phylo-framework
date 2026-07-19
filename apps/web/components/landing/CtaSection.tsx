import Link from "next/link";
import { ArrowRight, BookOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { getMethodContent } from "@/features/docs/content";
import { METHOD_IDS } from "@/features/docs/types";

export function CtaSection() {
  return (
    <section className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
      {/* supported methods */}
      <div className="mb-12 text-center">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Supported methods
        </p>
        <div className="mt-4 flex flex-wrap items-center justify-center gap-2">
          {METHOD_IDS.map((id) => (
            <Link
              key={id}
              href={`/documents/${id}`}
              className="rounded-full border px-4 py-1.5 text-sm font-medium text-foreground transition-colors hover:border-primary/40 hover:bg-accent"
            >
              {getMethodContent(id).displayName}
            </Link>
          ))}
        </div>
      </div>

      {/* closing CTA */}
      <div className="relative overflow-hidden rounded-2xl border bg-primary/5 px-6 py-12 text-center sm:px-12">
        <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
          <div className="absolute left-1/2 top-0 h-72 w-72 -translate-x-1/2 rounded-full bg-primary/10 blur-3xl" />
        </div>
        <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">
          Ready to uncover the evolutionary story encoded in your sequences?
        </h2>
        <p className="mx-auto mt-3 max-w-xl text-muted-foreground">
          Start a run from the dashboard, or check the documentation to learn how each method helps
          reveal the evolutionary patterns shaping your lineages.
        </p>
        <div className="mt-7 flex flex-wrap justify-center gap-3">
          <Link href="/dashboard">
            <Button size="lg" className="gap-2 px-6 text-base">
              Go to Dashboard
              <ArrowRight className="h-4 w-4" />
            </Button>
          </Link>
          <Link href="/documents">
            <Button size="lg" variant="outline" className="gap-2 px-6 text-base">
              <BookOpen className="h-4 w-4" />
              Read the docs
            </Button>
          </Link>
        </div>
      </div>
    </section>
  );
}
