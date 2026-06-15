"use client";

import { useEffect, useState } from "react";
import { fetchArtifactObjectUrl } from "@/features/runs/api";

type Props = {
  /** API preview path (e.g. /artifacts/{id}/preview). */
  previewUrl: string;
  alt: string;
  className?: string;
};

/**
 * Renders an image by streaming it through the authenticated API into an object
 * URL. Avoids base64 entirely and works with bearer-token auth (which a plain
 * <img src> cannot carry). Revokes the object URL on unmount/change.
 */
export default function ArtifactImage({ previewUrl, alt, className }: Props) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    setUrl(null);
    setFailed(false);
    fetchArtifactObjectUrl(previewUrl)
      .then((objectUrl) => {
        if (cancelled) {
          URL.revokeObjectURL(objectUrl);
          return;
        }
        created = objectUrl;
        setUrl(objectUrl);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [previewUrl]);

  if (failed) {
    return <div className="rounded border p-4 text-sm text-red-600">Failed to load image.</div>;
  }
  if (!url) {
    return <div className="rounded border p-4 text-sm text-muted-foreground">Loading image…</div>;
  }
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={url} alt={alt} className={className} />;
}
