import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  GitBranch,
  Upload,
  BarChart3,
  FolderTree,
  Zap,
  Shield,
  ArrowRight,
} from "lucide-react";

export default function Home() {
  return (
    <main className="flex flex-col min-h-[calc(100vh-3.5rem)]">
      {/* Hero */}
      <section className="flex flex-col items-center justify-center py-16 sm:py-24 px-4 sm:px-6">
        <div className="w-full max-w-2xl mx-auto text-center space-y-6 sm:space-y-8">
          <div className="inline-flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10 text-primary mb-2">
            <GitBranch className="w-8 h-8" />
          </div>
          <div className="space-y-3 sm:space-y-4">
            <h1 className="text-3xl font-bold tracking-tight sm:text-4xl md:text-5xl">
              Phylo Runner
            </h1>
            <p className="text-base text-muted-foreground sm:text-lg max-w-xl mx-auto">
              Run phylogeny methods on your data. Select a method, set parameters,
              upload your files, and generate trees — all in one place.
            </p>
          </div>
          <Link href="/dashboard">
            <Button size="lg" className="text-base px-6 sm:px-8 gap-2">
              Go to Dashboard
              <ArrowRight className="w-4 h-4" />
            </Button>
          </Link>
        </div>
      </section>

      {/* Features grid */}
      <section className="w-full max-w-4xl mx-auto px-4 pb-12 sm:pb-20 grid gap-4 grid-cols-1 sm:grid-cols-2">
        <Card className="border-border/80 hover:border-primary/30 transition-colors">
          <CardHeader className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <BarChart3 className="w-5 h-5" />
              </div>
              <CardTitle className="text-lg">Phylogeny methods</CardTitle>
            </div>
            <CardDescription>
              Dowser, GCtree, BrepPhylo, ClonalTree and more — with configurable parameters.
            </CardDescription>
          </CardHeader>
        </Card>
        <Card className="border-border/80 hover:border-primary/30 transition-colors">
          <CardHeader className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <Upload className="w-5 h-5" />
              </div>
              <CardTitle className="text-lg">Upload and run</CardTitle>
            </div>
            <CardDescription>
              Upload input files, set parameters, and get trees and results in one place.
            </CardDescription>
          </CardHeader>
        </Card>
        <Card className="border-border/80 hover:border-primary/30 transition-colors sm:col-span-2">
          <CardHeader className="space-y-2">
            <div className="flex items-center gap-2">
              <div className="p-2 rounded-lg bg-primary/10 text-primary">
                <FolderTree className="w-5 h-5" />
              </div>
              <CardTitle className="text-lg">Trees and artifacts</CardTitle>
            </div>
            <CardDescription>
              View interactive trees, download Newick files, and export result artifacts in one click.
            </CardDescription>
          </CardHeader>
        </Card>
      </section>

      {/* Bottom strip */}
      <section className="border-t bg-muted/30 py-8 px-4">
        <div className="max-w-4xl mx-auto flex flex-wrap items-center justify-center gap-6 sm:gap-10 text-sm text-muted-foreground">
          <span className="flex items-center gap-2">
            <Zap className="w-4 h-4 text-primary" />
            One-click runs
          </span>
          <span className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-primary" />
            Your data stays yours
          </span>
        </div>
      </section>
    </main>
  );
}
