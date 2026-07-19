"use client";

import { useCallback, useRef, useState } from "react";

export type Size = { width: number; height: number };

/**
 * Measure an element with a ResizeObserver via a CALLBACK ref, so it attaches
 * correctly even when the node mounts after the first render (e.g. after a
 * loading skeleton). Replaces the fixed-height scroll hacks — the zoom pane
 * derives its pixel size from the real element so `fitToView` fits the viewport.
 */
export function useContainerSize<T extends HTMLElement = HTMLDivElement>() {
  const [size, setSize] = useState<Size>({ width: 0, height: 0 });
  const observerRef = useRef<ResizeObserver | null>(null);

  const ref = useCallback((node: T | null) => {
    observerRef.current?.disconnect();
    observerRef.current = null;
    if (!node) return;
    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry) return;
      const { width, height } = entry.contentRect;
      setSize((prev) =>
        prev.width === width && prev.height === height ? prev : { width, height },
      );
    });
    ro.observe(node);
    observerRef.current = ro;
  }, []);

  return { ref, size };
}
