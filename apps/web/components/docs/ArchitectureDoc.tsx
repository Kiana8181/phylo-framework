import { Separator } from "@/components/ui/separator";
import { DiagramFigure } from "@/components/docs/DiagramFigure";

export function ArchitectureDoc() {
  return (
    <article className="mx-auto w-full max-w-5xl space-y-12">
      <header className="space-y-4">
        <h1 className="text-3xl font-bold tracking-tight">Architecture &amp; workflow</h1>
        <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground">
          How the pieces fit together, and what happens between uploading a dataset and viewing a
          result. Both diagrams are generated from an exact node/edge spec that mirrors the real
          services, ports, buckets and API routes in the repository.
        </p>
      </header>

      <Separator />

      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Architecture</h2>
          <p className="text-muted-foreground">
            The services, their ports, and the trust boundary between them.
          </p>
        </div>
        <DiagramFigure
          src="/docs/architecture.svg"
          alt="Architecture diagram. The browser (Next.js web UI on port 3000) talks only to the FastAPI API on port 8000. Inside the server's private network sit the API, the API worker, PostgreSQL on 5432, MinIO object storage on 9000/9001 with the phylo-datasets and phylo-artifacts buckets, and four method services: Dowser 8001, GCtree 8002, BrepPhylo 8003, ClonalTree 8004. The API reads run and file metadata from PostgreSQL and streams dataset and artifact bytes from MinIO to the browser. The worker claims queued runs from PostgreSQL, stages datasets from MinIO, and calls the method services over HTTP. Method services upload artifacts directly to MinIO with scoped credentials. MinIO is never exposed to the browser."
          caption={
            <>
              <strong className="text-foreground">In scope:</strong> the runtime services, their
              ports, the two MinIO buckets, and the request/data edges between them — including that
              the browser reaches object storage only by streaming through the API.{" "}
              <strong className="text-foreground">Omitted for clarity:</strong> auth providers,
              email/password-reset, the one-time MinIO bootstrap job, and the duplicated
              production-profile services (the <code>web-prod</code>/<code>api-prod</code> variants
              are the same shapes). See the repository <code>README.md</code> and{" "}
              <code>docs/DEPLOYMENT.md</code> for ops detail.
            </>
          }
        />
      </section>

      <Separator />

      <section className="space-y-6">
        <div className="space-y-1">
          <h2 className="text-2xl font-semibold tracking-tight">Workflow</h2>
          <p className="text-muted-foreground">
            From your side it is three steps: upload a dataset, choose a method, and collect the
            trees. This is what happens in between. The steps inside the dashed box run
            asynchronously in the worker (decoupled from your browser via a database-backed queue),
            so you can leave the page and the run continues.
          </p>
        </div>
        <DiagramFigure
          src="/docs/workflow.svg"
          alt="Workflow flowchart, top to bottom. The browser calls POST /uploads/init, then PUT /uploads/{id}/content which streams the file to the MinIO phylo-datasets bucket, then POST /runs?method={id} which creates a run row with status QUEUED. Asynchronously, the worker claims the queued run via a PostgreSQL lease, stages the dataset from MinIO into a run workspace, calls POST {METHOD_URL}/jobs, waits while the method computes and uploads its artifacts to the MinIO phylo-artifacts bucket with a manifest, polls GET /jobs/{id}/status then GET /jobs/{id}/result, and ingests the manifest into run_artifacts rows in PostgreSQL, setting status to DONE. The browser then polls GET /runs/{id}/status, /result and /artifacts, and fetches each artifact via GET /artifacts/{id}/preview or /download, which the API streams from MinIO."
          caption={
            <>
              <strong className="text-foreground">In scope:</strong> the successful upload → run →
              method job → artifact → fetch path, with the real routes and buckets.{" "}
              <strong className="text-foreground">Omitted:</strong> error, cancellation and retry
              paths; resumable-upload session bookkeeping; and per-method internal stages. The upload
              and run creation are synchronous; everything in the dashed box is asynchronous and
              survives a page reload.
            </>
          }
        />
      </section>
    </article>
  );
}
