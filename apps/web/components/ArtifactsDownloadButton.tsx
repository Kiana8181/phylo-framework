"use client";

import { Button } from "@/components/ui/button";

function b64ToBlob(b64Data: string, contentType = "application/zip") {
  const byteCharacters = atob(b64Data);
  const byteArrays = [];

  for (let offset = 0; offset < byteCharacters.length; offset += 1024) {
    const slice = byteCharacters.slice(offset, offset + 1024);
    const byteNumbers = new Array(slice.length);
    for (let i = 0; i < slice.length; i++) {
      byteNumbers[i] = slice.charCodeAt(i);
    }
    byteArrays.push(new Uint8Array(byteNumbers));
  }

  return new Blob(byteArrays, { type: contentType });
}

type Props = {
  base64: string | null | undefined;
  filename?: string;
};

export default function ArtifactsDownloadButton({ base64, filename }: Props) {
  if (!base64) return null;

  const handleClick = () => {
    try {
      const blob = b64ToBlob(base64);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename || "artifacts.zip";
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    } catch (e) {
      console.error("Download failed", e);
    }
  };

  return (
    <Button variant="outline" size="sm" onClick={handleClick}>
      Download artifacts.zip
    </Button>
  );
}
