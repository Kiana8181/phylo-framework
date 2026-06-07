"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { computeNodes, sanitizeLabel, type RenderNode } from "./runStageNodes";

function buildMermaidSource(nodes: RenderNode[], dark: boolean): string {
  const lines: string[] = ["flowchart TB"];
  nodes.forEach((node, i) => {
    const id = `n${i}`;
    lines.push(`  ${id}["${sanitizeLabel(node.label)}"]:::${node.state}`);
    if (i > 0) lines.push(`  n${i - 1} --> ${id}`);
  });

  // Theme-aware class definitions.
  const muted = dark ? "#1f2937" : "#f3f4f6";
  const mutedText = dark ? "#9ca3af" : "#6b7280";
  const border = dark ? "#374151" : "#d1d5db";
  const doneBg = dark ? "#064e3b" : "#dcfce7";
  const doneText = dark ? "#a7f3d0" : "#166534";
  const activeBg = dark ? "#1e3a8a" : "#dbeafe";
  const activeText = dark ? "#bfdbfe" : "#1e40af";
  const errBg = dark ? "#7f1d1d" : "#fee2e2";
  const errText = dark ? "#fecaca" : "#991b1b";

  lines.push(
    `  classDef pending fill:${muted},stroke:${border},color:${mutedText};`,
    `  classDef done fill:${doneBg},stroke:${doneText},color:${doneText};`,
    `  classDef active fill:${activeBg},stroke:${activeText},color:${activeText},stroke-width:3px,font-weight:bold;`,
    `  classDef error fill:${errBg},stroke:${errText},color:${errText},stroke-width:3px,font-weight:bold;`,
    `  classDef cancelled fill:${errBg},stroke:${errText},color:${errText},stroke-width:2px,stroke-dasharray:4 3;`,
  );

  return lines.join("\n");
}

export default function RunStageFlowchart({
  methodId,
  status,
  stage,
  stageMessage,
}: {
  methodId?: string | null;
  status?: string;
  stage?: string | null;
  progress?: number;
  stageMessage?: string | null;
}) {
  const reactId = useId();
  const diagramId = useMemo(
    () => `runflow-${reactId.replace(/[^a-zA-Z0-9]/g, "")}`,
    [reactId],
  );

  const [dark, setDark] = useState(false);
  useEffect(() => {
    if (typeof document === "undefined") return;
    setDark(document.documentElement.classList.contains("dark"));
  }, [status, stage]);

  const nodes = useMemo(
    () => computeNodes(methodId, status, stage),
    [methodId, status, stage],
  );

  const source = useMemo(() => buildMermaidSource(nodes, dark), [nodes, dark]);

  const [svg, setSvg] = useState<string | null>(null);
  const [renderFailed, setRenderFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setRenderFailed(false);
    (async () => {
      try {
        const mermaid = (await import("mermaid")).default;
        mermaid.initialize({
          startOnLoad: false,
          securityLevel: "strict",
          theme: dark ? "dark" : "default",
          flowchart: { htmlLabels: false, curve: "basis" },
        });
        const { svg: rendered } = await mermaid.render(diagramId, source);
        if (!cancelled) setSvg(rendered);
      } catch {
        if (!cancelled) {
          setSvg(null);
          setRenderFailed(true);
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, dark, diagramId]);

  const activeNode = nodes.find(
    (n) => n.state === "active" || n.state === "error" || n.state === "cancelled",
  );

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2 flex-wrap">
        <span className="text-xs font-medium text-muted-foreground">
          Pipeline
        </span>
        {activeNode && (
          <span className="text-xs text-muted-foreground truncate">
            {activeNode.label}
            {stageMessage ? ` — ${stageMessage}` : ""}
          </span>
        )}
      </div>

      {svg && !renderFailed ? (
        <div
          className="overflow-x-auto rounded-md border bg-muted/20 p-2 [&_svg]:max-w-full [&_svg]:h-auto"
          // Mermaid output is generated from sanitized labels with
          // securityLevel:"strict"; safe to inject.
          dangerouslySetInnerHTML={{ __html: svg }}
          aria-hidden
        />
      ) : null}

      {/* Accessible / fallback list of stages (also shown if render fails). */}
      <ol
        className={
          svg && !renderFailed
            ? "sr-only"
            : "flex flex-wrap gap-1.5 text-xs"
        }
      >
        {nodes.map((node, i) => (
          <li
            key={`${node.id}-${i}`}
            className={
              svg && !renderFailed
                ? undefined
                : `rounded border px-2 py-0.5 ${
                    node.state === "active"
                      ? "border-blue-400 bg-blue-50 font-medium text-blue-700 dark:bg-blue-950/40 dark:text-blue-300"
                      : node.state === "done"
                      ? "border-green-300 bg-green-50 text-green-700 dark:bg-green-950/40 dark:text-green-300"
                      : node.state === "error" || node.state === "cancelled"
                      ? "border-red-300 bg-red-50 text-red-700 dark:bg-red-950/40 dark:text-red-300"
                      : "border-border bg-muted text-muted-foreground"
                  }`
            }
          >
            {node.label}
            {node.state === "active" ? " (current)" : ""}
            {node.state === "done" ? " ✓" : ""}
          </li>
        ))}
      </ol>
    </div>
  );
}
