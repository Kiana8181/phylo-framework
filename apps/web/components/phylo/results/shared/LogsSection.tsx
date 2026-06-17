import type { RunLogEntry } from "@phylo/contracts";

/** Collapsible model logs (per-step command output). */
export default function LogsSection({ logs }: { logs?: RunLogEntry[] }) {
  if (!Array.isArray(logs) || logs.length === 0) return null;
  return (
    <details className="rounded border bg-card/50 p-3">
      <summary className="cursor-pointer text-sm font-medium">Show model logs</summary>
      <div className="mt-2 max-h-64 space-y-3 overflow-y-auto font-mono text-xs">
        {logs.map((log, index) => (
          <div key={`log-${index}`} className="border-b pb-2 last:border-0 last:pb-0">
            <div className="flex justify-between gap-2 text-[11px]">
              <span className="font-semibold">{log.step || `Step ${index + 1}`}</span>
              {typeof log.ok === "boolean" && (
                <span className={log.ok ? "text-emerald-500" : "text-red-500"}>
                  {log.ok ? "OK" : "FAIL"}
                </span>
              )}
            </div>
            {log.cmd && (
              <div className="mt-1 text-[11px] text-muted-foreground">
                <span className="font-semibold">cmd: </span>
                <code className="break-all">{log.cmd}</code>
              </div>
            )}
            {log.out && <pre className="mt-1 whitespace-pre-wrap">{log.out}</pre>}
          </div>
        ))}
      </div>
    </details>
  );
}
