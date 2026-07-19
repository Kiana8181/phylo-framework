"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { select } from "d3-selection";
import { zoom, zoomIdentity, type ZoomBehavior, type ZoomTransform } from "d3-zoom";
import { clamp } from "@/components/phylo/tree/core";

const MIN_SCALE = 0.05;
const MAX_SCALE = 8;
const FIT_PAD = 0.94; // leave a small margin so nothing touches the edges

export type Bounds = { x: number; y: number; width: number; height: number };

type UseZoomPanArgs = {
  /** The svg element, as state, so the behaviour (re)attaches when it mounts. */
  svgEl: SVGSVGElement | null;
  /** Natural content size (layout.width / layout.height). */
  contentWidth: number;
  contentHeight: number;
  /** Measured viewport size. */
  containerWidth: number;
  containerHeight: number;
  /** Bump to re-fit (model / layout identity change). */
  fitKey: unknown;
};

export type ZoomApi = {
  transform: ZoomTransform;
  zoomIn: () => void;
  zoomOut: () => void;
  resetZoom: () => void;
  fitToView: (bounds?: Bounds, animate?: boolean) => void;
  focusOn: (x: number, y: number, k?: number) => void;
  zoomTo: (t: ZoomTransform) => void;
};

const NOT_FITTED = Symbol("not-fitted");

/**
 * Single d3-zoom wrapper for every tree. The transform is applied to ONE inner
 * `<g>` (via the returned `transform`), never re-rendering per node on pan. State
 * is rAF-throttled so downstream recomputes at most once per frame.
 */
export function useZoomPan({
  svgEl,
  contentWidth,
  contentHeight,
  containerWidth,
  containerHeight,
  fitKey,
}: UseZoomPanArgs): ZoomApi {
  const [transform, setTransform] = useState<ZoomTransform>(zoomIdentity);
  const transformRef = useRef<ZoomTransform>(zoomIdentity);
  const rafRef = useRef<number | null>(null);
  const zbRef = useRef<ZoomBehavior<SVGSVGElement, unknown> | null>(null);

  // Attach the zoom behaviour whenever the svg element (re)mounts.
  useEffect(() => {
    if (!svgEl) return;
    const sel = select(svgEl);
    const zb = zoom<SVGSVGElement, unknown>()
      .scaleExtent([MIN_SCALE, MAX_SCALE])
      .on("zoom", (event) => {
        transformRef.current = event.transform;
        if (rafRef.current == null) {
          rafRef.current = requestAnimationFrame(() => {
            rafRef.current = null;
            setTransform(transformRef.current);
          });
        }
      });
    zbRef.current = zb;
    // d3-zoom preventDefaults wheel inside the pane, so the page never scrolls.
    sel.call(zb);
    return () => {
      sel.on(".zoom", null);
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
      zbRef.current = null;
    };
  }, [svgEl]);

  const applyTransform = useCallback(
    (t: ZoomTransform, animate: boolean) => {
      const zb = zbRef.current;
      if (!svgEl || !zb) return;
      const sel = select(svgEl);
      if (animate) sel.transition().duration(400).call(zb.transform, t);
      else sel.call(zb.transform, t);
    },
    [svgEl],
  );

  const fitToView = useCallback(
    (bounds?: Bounds, animate = false) => {
      if (containerWidth <= 0 || containerHeight <= 0) return;
      const bx = bounds?.x ?? 0;
      const by = bounds?.y ?? 0;
      const bw = bounds?.width ?? contentWidth;
      const bh = bounds?.height ?? contentHeight;
      if (bw <= 0 || bh <= 0) return;
      const k = clamp(
        Math.min(containerWidth / bw, containerHeight / bh) * FIT_PAD,
        MIN_SCALE,
        MAX_SCALE,
      );
      const tx = containerWidth / 2 - k * (bx + bw / 2);
      const ty = containerHeight / 2 - k * (by + bh / 2);
      applyTransform(zoomIdentity.translate(tx, ty).scale(k), animate);
    },
    [applyTransform, containerHeight, containerWidth, contentHeight, contentWidth],
  );

  const focusOn = useCallback(
    (x: number, y: number, k?: number) => {
      if (containerWidth <= 0 || containerHeight <= 0) return;
      const scale = clamp(k ?? transformRef.current.k, MIN_SCALE, MAX_SCALE);
      const tx = containerWidth / 2 - scale * x;
      const ty = containerHeight / 2 - scale * y;
      applyTransform(zoomIdentity.translate(tx, ty).scale(scale), true);
    },
    [applyTransform, containerHeight, containerWidth],
  );

  const zoomBy = useCallback(
    (factor: number) => {
      const zb = zbRef.current;
      if (!svgEl || !zb) return;
      select(svgEl).transition().duration(200).call(zb.scaleBy, factor);
    },
    [svgEl],
  );

  const zoomIn = useCallback(() => zoomBy(1.3), [zoomBy]);
  const zoomOut = useCallback(() => zoomBy(1 / 1.3), [zoomBy]);
  const resetZoom = useCallback(() => fitToView(undefined, true), [fitToView]);
  const zoomTo = useCallback((t: ZoomTransform) => applyTransform(t, true), [applyTransform]);

  // Fit on first valid measurement and whenever model/layout identity changes.
  const fittedKeyRef = useRef<unknown>(NOT_FITTED);
  useEffect(() => {
    if (containerWidth <= 0 || containerHeight <= 0) return;
    if (fittedKeyRef.current === fitKey) return;
    fittedKeyRef.current = fitKey;
    fitToView(undefined, false);
  }, [fitKey, containerWidth, containerHeight, fitToView]);

  return { transform, zoomIn, zoomOut, resetZoom, fitToView, focusOn, zoomTo };
}
