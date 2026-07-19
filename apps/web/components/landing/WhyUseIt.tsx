import { Columns3, RotateCcw, GitCompare } from "lucide-react";

type Pillar = { icon: typeof Columns3; title: string; body: string };

const PILLARS: Pillar[] = [
  {
    icon: Columns3,
    title: "Standardized inputs, not edited files",
    body: "Every method expects different column names. Map your dataset to each method's expected inputs once — the original file is never modified, and never re-uploaded.",
  },
  {
    icon: RotateCcw,
    title: "Every run regenerates exactly",
    body: "Parameters and the random seed are recorded with every run, so the same input yields the same tree — or carry the settings forward and change exactly one value.",
  },
  {
    icon: GitCompare,
    title: "Compare methods, not file formats",
    body: "Trace the same sequence through four independent reconstructions and see where each method places it. The comparison is the point.",
  },
];

export function WhyUseIt() {
  return (
    <section className="border-b bg-muted/30">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="mx-auto max-w-2xl space-y-3 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Why use Phylo Runner?</h2>
          <p className="text-lg text-muted-foreground">
            The methods are powerful but hard to work with, and each expects its own inputs. Phylo
            Runner standardizes the way in, so the differences you see between methods come from the
            biology — not from your file format.
          </p>
        </div>
        <div className="mt-12 grid gap-8 md:grid-cols-3">
          {PILLARS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="space-y-3">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="text-base leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
