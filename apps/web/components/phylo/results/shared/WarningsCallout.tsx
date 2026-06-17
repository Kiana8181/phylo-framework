import type { RunWarning } from "@phylo/contracts";

/** Yellow callout listing run warnings (strings or structured {code,message,treeId}). */
export default function WarningsCallout({ warnings }: { warnings?: RunWarning[] }) {
  const list = Array.isArray(warnings) ? warnings : [];
  if (list.length === 0) return null;
  return (
    <div className="space-y-1 rounded border bg-yellow-50 p-3 text-sm text-yellow-900 dark:bg-yellow-950/30 dark:text-yellow-200">
      {list.map((warning, idx) => {
        if (typeof warning === "string") return <div key={`warn-${idx}`}>• {warning}</div>;
        const code = String(warning.code ?? "").trim();
        const msg = String(warning.message ?? "").trim();
        const treeId = String(warning.treeId ?? "").trim();
        return (
          <div key={`warn-${idx}`}>
            • {code ? `[${code}] ` : ""}
            {msg || "Warning"}
            {treeId ? ` (tree: ${treeId})` : ""}
          </div>
        );
      })}
    </div>
  );
}
