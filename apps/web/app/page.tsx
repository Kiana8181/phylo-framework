"use client";
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, MethodInfo } from "@/lib/api";
import { Card } from "@/components/ui/card";
import FormBuilder from "@/components/ui/FormBuilder";

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

  useEffect(() => {
    if (!runId) return;
    const t = setInterval(async () => {
      const s = await api.getRunStatus(runId);
      setStatus(
        `${s.status}${s.progress ? ` (${s.progress}%)` : ""}${
          s.message ? ` - ${s.message}` : ""
        }`
      );
      if (s.status === "DONE" || s.status === "ERROR") clearInterval(t);
    }, 1500);
    return () => clearInterval(t);
  }, [runId]);

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
            onClick={() => setSelected(m)}
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
              files.forEach((f) => fd.append("files", f));
              const res = await api.createRun(spec.id, fd);
              setRunId(res.run_id);
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
    </main>
  );
}
