"use client";

import { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import ArtifactsDownloadButton from "@/components/ArtifactsDownloadButton";
import { RunsApi } from "@/features/runs/api";
import type { RunArtifact } from "@phylo/contracts";

function formatSize(bytes?: number | null): string {
  if (!bytes || bytes <= 0) return "";
  const units = ["B", "KB", "MB", "GB"];
  let n = bytes;
  let i = 0;
  while (n >= 1024 && i < units.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i === 0 ? 0 : 1)} ${units[i]}`;
}

type Props = { runId?: string | null };

/**
 * Lists a run's downloadable artifacts (metadata only). Binaries are streamed
 * lazily through the authenticated API when the user clicks download — the
 * page never eagerly fetches ZIP/file content.
 */
export default function RunArtifactsSection({ runId }: Props) {
  const [artifacts, setArtifacts] = useState<RunArtifact[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!runId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    RunsApi.artifacts(runId)
      .then((res) => {
        if (!cancelled) setArtifacts(res?.artifacts ?? []);
      })
      .catch((err) => {
        console.error("[artifacts] load failed", err);
        if (!cancelled) setError("Could not load artifacts.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (!runId) return null;
  if (loading) {
    return (
      <Card className="p-4">
        <div className="text-sm text-muted-foreground">Loading artifacts…</div>
      </Card>
    );
  }
  if (error) {
    return (
      <Card className="p-4">
        <div className="text-sm text-red-600">{error}</div>
      </Card>
    );
  }
  if (!artifacts.length) return null;

  // Surface the bundle (ZIP) first, then everything else.
  const ordered = [...artifacts].sort((a, b) => {
    const az = a.artifact_kind === "zip" ? 0 : 1;
    const bz = b.artifact_kind === "zip" ? 0 : 1;
    return az - bz;
  });

  return (
    <Card className="p-4 space-y-3">
      <h4 className="font-medium">Downloads</h4>
      <ul className="divide-y">
        {ordered.map((a) => (
          <li key={a.id} className="flex items-center justify-between gap-3 py-2">
            <div className="min-w-0">
              <div className="truncate text-sm font-medium">{a.filename}</div>
              <div className="text-xs text-muted-foreground">
                {a.artifact_role || a.artifact_kind}
                {a.size_bytes ? ` · ${formatSize(a.size_bytes)}` : ""}
              </div>
            </div>
            <ArtifactsDownloadButton
              downloadUrl={a.download_url}
              filename={a.filename}
              label="Download"
            />
          </li>
        ))}
      </ul>
    </Card>
  );
}
