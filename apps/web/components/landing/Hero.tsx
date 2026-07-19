import Link from "next/link";
import { ArrowRight, BookOpen, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { PhyloHeroArt } from "./PhyloHeroArt";

export function Hero() {
  return (
    <section className="relative overflow-hidden border-b">
      {/* token-based gradient backdrop */}
      <div aria-hidden className="pointer-events-none absolute inset-0 -z-10">
        <div className="absolute -left-40 -top-40 h-[28rem] w-[28rem] rounded-full bg-primary/15 blur-3xl" />
        <div className="absolute right-0 top-1/3 h-[24rem] w-[24rem] rounded-full bg-chart-2/10 blur-3xl" />
      </div>

      <div className="mx-auto grid max-w-6xl items-center gap-10 px-4 py-16 sm:px-6 sm:py-24 lg:grid-cols-2">
        <div className="space-y-6">
          <span className="inline-flex items-center gap-2 rounded-full border bg-background/60 px-3 py-1 text-xs font-medium text-muted-foreground backdrop-blur">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            Standardized · Reproducible · Four methods, one workflow
          </span>
          <h1 className="text-4xl font-bold tracking-tight sm:text-5xl md:text-6xl">
            A unified workflow for{" "}
            <span className="text-primary">B-cell lineage reconstruction</span>
          </h1>
          <p className="max-w-xl text-lg leading-relaxed text-muted-foreground">
            Phylo Runner is a unified, reproducible framework for standardized B-cell lineage
            reconstruction across multiple phylogenetic methods. Run Dowser, GCtree, BrepPhylo and
            ClonalTree over one dataset through one workflow — every run recorded with its parameters
            and its random seed, so any result can be regenerated exactly.
          </p>
          <div className="flex flex-wrap gap-3">
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

        <div className="relative">
          <PhyloHeroArt className="mx-auto w-full max-w-lg text-primary" />
        </div>
      </div>
    </section>
  );
}
