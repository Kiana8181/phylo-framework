import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { DiagramFigure } from "@/components/docs/DiagramFigure";
import { getMethodDocModel } from "@/features/docs/loader";
import { getMethodContent } from "@/features/docs/content";
import { METHOD_IDS } from "@/features/docs/types";
import { ARTIFACT_KINDS, getBiologicalOutputs } from "@/features/docs/io";

export function DataModelDoc() {
  const methods = METHOD_IDS.map((id) => {
    const content = getMethodContent(id);
    return {
      id,
      name: content.displayName,
      tagline: content.tagline,
      lede: content.summary[0],
      capabilities: content.capabilities,
      formats: getMethodDocModel(id).acceptFormats,
      outputs: getBiologicalOutputs(id),
    };
  });

  return (
    <article className="mx-auto w-full max-w-5xl space-y-12">
      <header className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Data model &amp; I/O specification</h1>
        <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground">
          What your data looks like as it moves through the framework, and what biology each method
          asks for and gives back. If you work with B-cell receptor repertoires, this is the page
          that maps your sequences and clones onto trees, ancestral sequences, and the evolutionary
          analyses you can read off them.
        </p>
      </header>

      <Separator />

      {/* Conceptual model — biology first */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">How your data is organised</h2>
          <p className="text-muted-foreground">
            The framework works in the same units you already think in — a repertoire of sequences,
            grouped into clonal lineages, each reconstructed as a lineage tree.
          </p>
        </div>
        <DiagramFigure
          src="/docs/study-model.svg"
          alt="Conceptual data flow. Your dataset is a B-cell receptor repertoire: an AIRR or Change-O table of aligned antibody sequences. Sequences are grouped into clonal lineages (clones) — each clone is one B-cell lineage. One of the four methods (Dowser, GCtree, BrepPhylo, ClonalTree) performs phylogenetic inference to build a lineage tree per clone, with the germline at the root, the observed sequences at the tips, and inferred ancestral sequences at the internal nodes. From each tree the framework produces reconstructed sequences (germline and ancestral), evolutionary analyses (isotype or class switching, selection, measurable evolution over time), and figures and tables (lineage-tree plots, per-clone tables, downloadable bundles)."
          caption={
            <>
              Your <strong className="text-foreground">dataset</strong> is a repertoire of aligned
              BCR sequences. Sequences are grouped into <strong className="text-foreground">clones</strong>{" "}
              (clonal lineages). Each clone becomes a{" "}
              <strong className="text-foreground">lineage tree</strong> — germline at the root, your
              observed sequences at the tips, and inferred ancestral sequences at the internal nodes
              — from which the framework derives reconstructed sequences, evolutionary analyses, and
              figures. The four methods differ in how they build that tree, but they share this shape.
            </>
          }
        />
      </section>

      <Separator />

      {/* Per-method I/O in biological terms */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">
            What each method takes in and gives back
          </h2>
          <p className="text-muted-foreground">
            All four start from the same kind of data — clonally-related, aligned BCR sequences — and
            return a lineage tree per clone, but they emphasise different biology. The exact input{" "}
            <em>columns</em> are on the{" "}
            <Link href="/documents/data-requirements" className="text-primary hover:underline">
              Data requirements
            </Link>{" "}
            page; here is the biology.
          </p>
        </div>

        <div className="space-y-8">
          {methods.map((m) => (
            <div key={m.id} className="space-y-4 rounded-lg border p-5">
              <div className="space-y-1">
                <h3 className="text-lg font-semibold">
                  <Link href={`/documents/${m.id}`} className="hover:text-primary hover:underline">
                    {m.name}
                  </Link>
                </h3>
                <p className="text-sm text-muted-foreground">{m.tagline}</p>
              </div>
              <p className="text-sm leading-relaxed text-muted-foreground">{m.lede}</p>

              <div className="grid gap-6 sm:grid-cols-2">
                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Takes in</h4>
                  <div className="flex flex-wrap gap-1.5">
                    {m.formats.length ? (
                      m.formats.map((fmt) => (
                        <Badge key={fmt} variant="secondary">
                          {fmt}
                        </Badge>
                      ))
                    ) : (
                      <span className="text-sm text-muted-foreground">—</span>
                    )}
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Clonally-related, aligned BCR sequences with their clone assignments (and, where
                    the method uses them, germline references and V/J calls).
                  </p>
                </div>

                <div className="space-y-2">
                  <h4 className="text-sm font-semibold">Gives back</h4>
                  <ul className="space-y-1 text-sm text-muted-foreground">
                    {m.outputs.map((o) => (
                      <li key={o.key} className="leading-snug">
                        {o.label}
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              <div className="space-y-1.5">
                <h4 className="text-sm font-semibold">Notable analyses</h4>
                <div className="flex flex-wrap gap-1.5">
                  {m.capabilities.map((cap) => (
                    <Badge key={cap} variant="outline" className="font-normal">
                      {cap}
                    </Badge>
                  ))}
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <Separator />

      {/* Downloadable outputs */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Outputs you can download</h2>
          <p className="text-muted-foreground">
            Every run keeps its outputs so you can revisit, compare and export them. Beyond the
            on-screen trees, a run produces files of these kinds:
          </p>
        </div>
        <ul className="grid gap-2 text-sm text-muted-foreground sm:grid-cols-2">
          <li>
            <Badge variant="outline">image</Badge> &mdash; rendered lineage-tree plots (PNG/SVG/PDF)
          </li>
          <li>
            <Badge variant="outline">newick</Badge> &mdash; the trees themselves, for use in other
            tools
          </li>
          <li>
            <Badge variant="outline">fasta</Badge> &mdash; germline and reconstructed ancestral
            sequences
          </li>
          <li>
            <Badge variant="outline">table</Badge> &mdash; per-clone / per-node data tables (TSV/CSV)
          </li>
          <li>
            <Badge variant="outline">json</Badge> &mdash; structured node metadata and statistics
          </li>
          <li>
            <Badge variant="outline">zip</Badge> &mdash; a bundle of everything for one run
          </li>
        </ul>
        <p className="text-sm text-muted-foreground">
          (Full set of artifact kinds: {ARTIFACT_KINDS.join(", ")}.) You download or preview these
          from the run in the dashboard — the framework serves the files to you; you never touch the
          storage layer directly.
        </p>
        <Link
          href="/documents/data-requirements"
          className="inline-flex items-center gap-1 text-sm font-medium text-primary hover:underline"
        >
          See the full input-column matrix
          <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      </section>

      <Separator />

      {/* Technical schema — demoted, clearly optional for a biologist */}
      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Under the hood: database schema</h2>
          <p className="text-muted-foreground">
            For developers and reproducibility: the persistent entities that record every dataset,
            run and output. A biologist can safely skip this — it is the storage counterpart of the
            conceptual model above, not new biology.
          </p>
        </div>
        <DiagramFigure
          src="/docs/data-model.svg"
          alt="Entity-relationship diagram of the PostgreSQL schema. A users table (id, email, username) has one-to-many relationships to runs, files and upload_sessions. A runs table (id, user_id, input_file_id, method_id, status, stage, params JSONB, result JSONB) has one-to-many relationships to run_trees (tree_index, tree_id, newick), run_artifacts (object_key, artifact_kind, artifact_role, is_previewable, storage_state), job_queue (job_id, status), and to files as run outputs. A run references its input dataset via runs.input_file_id, and an upload_session references its committed file via final_file_id."
          caption={
            <>
              <strong className="text-foreground">In scope:</strong> the persistent entities and
              their foreign-key relationships (key columns only). <code>runs.result</code> is a
              lightweight summary; the actual sequences, trees and figures are stored as files
              (<code>run_artifacts</code>), while <code>run_trees</code> holds the per-clone Newick
              and node metadata used to draw and trace lineages.
            </>
          }
        />
      </section>
    </article>
  );
}
