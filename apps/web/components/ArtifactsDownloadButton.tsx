"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { fetchArtifactObjectUrl } from "@/features/runs/api";
import { notify } from "@/lib/notify";

type Props = {
  /** API path to the artifact download endpoint (e.g. /artifacts/{id}/download). */
  downloadUrl: string;
  filename?: string;
  label?: string;
};

/**
 * Downloads an artifact by streaming it through the authenticated API and
 * triggering a browser download from an object URL. No base64 is involved.
 */
export default function ArtifactsDownloadButton({ downloadUrl, filename, label }: Props) {
  const [busy, setBusy] = useState(false);
  if (!downloadUrl) return null;

  const handleClick = async () => {
    setBusy(true);
    try {
      const url = await fetchArtifactObjectUrl(downloadUrl);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "artifact";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      notify.error("Download failed", "Could not download the artifact.");
      console.error("Artifact download failed", e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant="outline" size="sm" onClick={handleClick} disabled={busy}>
      {busy ? "Downloading…" : label || `Download ${filename || "artifact"}`}
    </Button>
  );
}
