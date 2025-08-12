"use client";
import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";
import TreeSVG from "@/components/ui/TreeSVG";
import { api, MethodInfo } from "@/lib/api";
import { cleanNewick } from "@/lib/newick";
import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export default function Home() {
  const { data: methods } = useQuery({
    queryKey: ["methods"],
    queryFn: api.listMethods,
  });
  const [selected, setSelected] = useState<MethodInfo | null>(null);
  const { data: spec } = useQuery({
    queryKey: ["spec", selected?.id],
    queryFn: () => api.getSpec(selected!.id),
    enabled: !!selected,
  });

  const [files, setFiles] = useState<File[]>([]);
  const [runId, setRunId] = useState<string | null>(null);
  const [status, setStatus] = useState<string>("");
  const [result, setResult] = useState<{
    ok: boolean;
    trees: string[];
    clones: any;
    stats: any;
    annotations: any;
    figures: any;
  } | null>(null);

  useEffect(() => {
    if (!runId) return;
    const t = setInterval(async () => {
      const s = await api.getRunStatus(runId);
      setStatus(
        `${s.status}${s.progress ? ` (${s.progress}%)` : ""}${
          s.message ? ` - ${s.message}` : ""
        }`
      );
      if (s.status === "DONE") {
        clearInterval(t);
        const r = await api.getRunResult(runId);
        setResult(r);
      }
      if (s.status === "ERROR") clearInterval(t);
    }, 1200);
    return () => clearInterval(t);
  }, [runId]);

  const cloneRows =
    result?.clones?.clone_id?.map((id: string, i: number) => ({
      id,
      seqs: result?.clones?.seqs?.[i],
    })) ?? [];

  return (
    <main className="mx-auto max-w-5xl p-6 space-y-8">
      <h1 className="text-2xl font-semibold">Phylo Runner</h1>

      <section className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {methods?.map((m) => (
          <Card
            key={m.id}
            className={`p-4 cursor-pointer border ${
              selected?.id === m.id ? "ring-2 ring-blue-500" : ""
            }`}
            onClick={() => {
              setSelected(m);
              setResult(null);
              setRunId(null);
              setStatus("");
            }}
          >
            <div className="font-medium">{m.name}</div>
            <div className="text-xs text-muted-foreground">v{m.version}</div>
          </Card>
        ))}
      </section>

      {spec && (
        <section className="space-y-4">
          <h2 className="text-xl font-medium">{spec.name} parameters</h2>
          <FormBuilder
            schema={{ ...spec.paramSchema, uiHints: spec.uiHints }}
            onSubmit={async (params) => {
              const fd = new FormData();
              fd.set("params", JSON.stringify(params));
              files.forEach((f) => fd.append("file", f));
              const res = await api.createRun(spec.id, fd);
              setRunId(res.run_id);
              setResult(null);
            }}
          />
        </section>
      )}

      {spec && (
        <section className="space-y-2">
          <h3 className="font-medium">Upload data</h3>
          <input
            type="file"
            multiple
            onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            className="block"
            accept=".csv,.tsv,.fasta,.fa,.rds,.rda,.txt"
          />
          <div className="text-xs text-muted-foreground">
            Accepted: {spec.accepts.join(", ")}
          </div>
        </section>
      )}

      {runId && (
        <section className="space-y-2">
          <div className="text-sm">Run ID: {runId}</div>
          <div className="text-sm">Status: {status}</div>
        </section>
      )}

      {result && (
        <section className="space-y-6">
          <h3 className="text-lg font-medium">Results</h3>

          {/* Trees */}
          <div className="space-y-8">
            {result.trees?.length ? (
              result?.trees?.map((raw, i) => {
                const nwk = cleanNewick(raw);
                const ann = result?.annotations?.[i] ?? [];
                return (
                  <div key={i} className="space-y-2">
                    {/* Dowser PNG (exact) */}
                    {result?.figures?.png_base64?.[i] && (
                      <img
                        src={`data:image/png;base64,${result.figures.png_base64[i]}`}
                        className="rounded border bg-white"
                        alt={`Dowser tree ${i + 1}`}
                      />
                    )}
                    {/* Interactive (colored) */}
                    <TreeSVG
                      newick={cleanNewick(result.trees[i])} // or raw string; component sanitizes too
                      annotations={result.annotations?.[i]} // enables colored tips
                      showLabels={true}
                    />
                  </div>
                );
              })
            ) : (
              <div className="text-sm text-muted-foreground">
                No trees returned.
              </div>
            )}
          </div>

          {/* Extra info from Dowser */}
          <div className="space-y-2">
            <h4 className="font-medium">Clone summary</h4>
            {cloneRows.length ? (
              <div className="overflow-x-auto rounded border">
                <table className="w-full text-sm">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left">Clone ID</th>
                      <th className="px-3 py-2 text-left">Seqs</th>
                    </tr>
                  </thead>
                  <tbody>
                    {cloneRows.map((r: any, i: any) => (
                      <tr key={i} className="border-t">
                        <td className="px-3 py-2">{r.id}</td>
                        <td className="px-3 py-2">{r.seqs}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="text-sm text-muted-foreground">
                No clone metadata found.
              </div>
            )}
          </div>

          {result?.stats && (
            <div className="text-sm text-muted-foreground">
              Clones: {result.stats.n_clones} • Trees: {result.stats.n_trees} •
              Seqs: {result.stats.total_seqs}
            </div>
          )}

          {/* Raw Newick (optional) */}
          <details className="rounded border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Show Newick text
            </summary>
            <div className="mt-2 space-y-2">
              {result.trees.map((nwk: string, i: number) => (
                <pre key={i} className="whitespace-pre-wrap text-xs">
                  {nwk}
                </pre>
              ))}
            </div>
          </details>
        </section>
      )}
    </main>
  );
}
