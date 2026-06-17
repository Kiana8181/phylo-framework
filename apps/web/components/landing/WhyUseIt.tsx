import { Boxes, Database, GitCompare } from "lucide-react";

type Pillar = { icon: typeof Boxes; title: string; body: string };

const PILLARS: Pillar[] = [
  {
    icon: Boxes,
    title: "No setup headaches",
    body: "The raw tools have no friendly environment and are awkward to install and run. Here they share one guided form — pick a method, fill in parameters, and go.",
  },
  {
    icon: Database,
    title: "One dataset, every method",
    body: "Upload TSV or CSV once and run all four methods — including GCtree, which natively takes no tabular input — through behind-the-scenes conversion with no data loss.",
  },
  {
    icon: GitCompare,
    title: "Compare with confidence",
    body: "Results are saved and revisitable. Trace a sequence across runs side by side, and carry parameters into the next run to re-run with a single change.",
  },
];

export function WhyUseIt() {
  return (
    <section className="border-b bg-muted/30">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:px-6">
        <div className="mx-auto max-w-2xl space-y-3 text-center">
          <h2 className="text-3xl font-bold tracking-tight">Why use Phylo Runner?</h2>
          <p className="text-muted-foreground">
            The methods are powerful but hard to work with. Phylo Runner removes the friction so you
            can focus on the biology.
          </p>
        </div>
        <div className="mt-12 grid gap-8 md:grid-cols-3">
          {PILLARS.map(({ icon: Icon, title, body }) => (
            <div key={title} className="space-y-3">
              <div className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-primary/10 text-primary">
                <Icon className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-semibold">{title}</h3>
              <p className="leading-relaxed text-muted-foreground">{body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
