"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

type TreeZoomPaneProps = {
  children: React.ReactNode;
  className?: string;
  fitKey?: string | number;
  minScale?: number;
  maxScale?: number;
  zoomStep?: number;
  requireModifierForWheelZoom?: boolean;
};

/** Imperative controls for focusing/zooming the pane on a tree coordinate. */
export type TreeZoomPaneHandle = {
  /** Center `(svgX, svgY)` (SVG user units) in the viewport at `scale`. */
  focusOnPoint: (svgX: number, svgY: number, scale: number) => void;
  fitToView: () => void;
};

type Transform = {
  scale: number;
  x: number;
  y: number;
};

type DragState = {
  pointerId: number;
  startClientX: number;
  startClientY: number;
  startX: number;
  startY: number;
};

const DEFAULT_TRANSFORM: Transform = {
  scale: 1,
  x: 0,
  y: 0,
};

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

function getSvgSize(target: SVGSVGElement): { width: number; height: number } | null {
  const viewBox = target.viewBox?.baseVal;
  if (viewBox && viewBox.width > 0 && viewBox.height > 0) {
    return { width: viewBox.width, height: viewBox.height };
  }

  const widthAttr = Number(target.getAttribute("width"));
  const heightAttr = Number(target.getAttribute("height"));
  if (Number.isFinite(widthAttr) && Number.isFinite(heightAttr) && widthAttr > 0 && heightAttr > 0) {
    return { width: widthAttr, height: heightAttr };
  }

  const widthBase = target.width?.baseVal?.value;
  const heightBase = target.height?.baseVal?.value;
  if (Number.isFinite(widthBase) && Number.isFinite(heightBase) && widthBase > 0 && heightBase > 0) {
    return { width: widthBase, height: heightBase };
  }

  return null;
}

const TreeZoomPane = forwardRef<TreeZoomPaneHandle, TreeZoomPaneProps>(function TreeZoomPane({
  children,
  className,
  fitKey,
  minScale = 0.05,
  maxScale = 4,
  zoomStep = 1.2,
  requireModifierForWheelZoom = true,
}: TreeZoomPaneProps, ref) {
  const viewportRef = useRef<HTMLDivElement>(null);
  const transformRef = useRef<Transform>({ ...DEFAULT_TRANSFORM });
  const dragRef = useRef<DragState | null>(null);
  const wheelRafRef = useRef<number | null>(null);
  const panRafRef = useRef<number | null>(null);
  const wheelDeltaRef = useRef(0);
  const pendingPanRef = useRef<{ x: number; y: number } | null>(null);
  const lastWheelEventRef = useRef<WheelEvent | null>(null);
  const [zoomPercent, setZoomPercent] = useState(100);
  const [isPanning, setIsPanning] = useState(false);

  const getZoomTarget = useCallback((): SVGSVGElement | null => {
    const viewport = viewportRef.current;
    if (!viewport) return null;
    return viewport.querySelector<SVGSVGElement>('svg[data-tree-zoom-target="true"]');
  }, []);

  const applyTransform = useCallback(() => {
    const target = getZoomTarget();
    if (!target) return;
    const { x, y, scale } = transformRef.current;
    target.style.transformOrigin = "0 0";
    target.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
    target.style.willChange = "transform";
  }, [getZoomTarget]);

  const zoomAroundPoint = useCallback(
    (requestedScale: number, clientX: number, clientY: number) => {
      const target = getZoomTarget();
      if (!target) return;

      const current = transformRef.current;
      const nextScale = clamp(requestedScale, minScale, maxScale);
      if (nextScale === current.scale) return;

      const rect = target.getBoundingClientRect();
      const offsetX = clientX - rect.left;
      const offsetY = clientY - rect.top;
      const worldX = offsetX / current.scale;
      const worldY = offsetY / current.scale;

      const nextX = clientX - rect.left + current.x - worldX * nextScale;
      const nextY = clientY - rect.top + current.y - worldY * nextScale;

      transformRef.current = {
        scale: nextScale,
        x: nextX,
        y: nextY,
      };
      applyTransform();
      setZoomPercent(Math.round(nextScale * 100));
    },
    [applyTransform, getZoomTarget, maxScale, minScale],
  );

  const zoomAtTargetCenter = useCallback(
    (factor: number) => {
      const target = getZoomTarget();
      if (!target) return;
      const rect = target.getBoundingClientRect();
      const centerX = rect.left + rect.width / 2;
      const centerY = rect.top + rect.height / 2;
      zoomAroundPoint(transformRef.current.scale * factor, centerX, centerY);
    },
    [getZoomTarget, zoomAroundPoint],
  );

  const fitToView = useCallback(() => {
    const target = getZoomTarget();
    if (!target) return;

    const size = getSvgSize(target);
    if (!size) return;

    const host = (target.parentElement as HTMLElement | null) ?? viewportRef.current;
    if (!host) return;
    const hostWidth = host.clientWidth;
    const hostHeight = host.clientHeight;
    if (hostWidth <= 0 || hostHeight <= 0) return;

    const fitScale = clamp(
      Math.min(hostWidth / size.width, hostHeight / size.height),
      minScale,
      maxScale,
    );

    transformRef.current = {
      scale: fitScale,
      x: (hostWidth - size.width * fitScale) / 2,
      y: (hostHeight - size.height * fitScale) / 2,
    };
    applyTransform();
    setZoomPercent(Math.round(fitScale * 100));
  }, [applyTransform, getZoomTarget, maxScale, minScale]);

  const resetTransform = useCallback(() => {
    fitToView();
  }, [fitToView]);

  const focusOnPoint = useCallback(
    (svgX: number, svgY: number, requestedScale: number) => {
      const target = getZoomTarget();
      if (!target) return;
      const host = (target.parentElement as HTMLElement | null) ?? viewportRef.current;
      if (!host) return;
      const s = clamp(requestedScale, minScale, maxScale);
      transformRef.current = {
        scale: s,
        x: host.clientWidth / 2 - svgX * s,
        y: host.clientHeight / 2 - svgY * s,
      };
      applyTransform();
      setZoomPercent(Math.round(s * 100));
    },
    [applyTransform, getZoomTarget, maxScale, minScale],
  );

  useImperativeHandle(ref, () => ({ focusOnPoint, fitToView }), [focusOnPoint, fitToView]);

  useEffect(() => {
    applyTransform();
  }, [applyTransform, children]);

  useEffect(() => {
    const rafId = requestAnimationFrame(() => {
      fitToView();
    });
    return () => {
      cancelAnimationFrame(rafId);
    };
  }, [fitToView, fitKey]);

  useEffect(() => {
    return () => {
      if (wheelRafRef.current !== null) {
        cancelAnimationFrame(wheelRafRef.current);
      }
      if (panRafRef.current !== null) {
        cancelAnimationFrame(panRafRef.current);
      }
    };
  }, []);

  const flushWheel = useCallback(() => {
    wheelRafRef.current = null;
    const lastEvent = lastWheelEventRef.current;
    if (!lastEvent || wheelDeltaRef.current === 0) return;

    const magnitude = wheelDeltaRef.current;
    wheelDeltaRef.current = 0;
    lastWheelEventRef.current = null;

    const factor = Math.exp(-magnitude * 0.0015);
    zoomAroundPoint(
      transformRef.current.scale * factor,
      lastEvent.clientX,
      lastEvent.clientY,
    );
  }, [zoomAroundPoint]);

  const commitPendingPan = useCallback(() => {
    const pending = pendingPanRef.current;
    if (!pending) return;
    pendingPanRef.current = null;
    transformRef.current = {
      ...transformRef.current,
      x: pending.x,
      y: pending.y,
    };
    applyTransform();
  }, [applyTransform]);

  const flushPan = useCallback(() => {
    panRafRef.current = null;
    commitPendingPan();
  }, [commitPendingPan]);

  return (
    <div className={cn("relative flex h-full min-h-[420px] flex-col", className)}>
      <div className="flex items-center justify-end gap-2 pb-2" data-zoom-control="true">
        <span className="w-14 text-right text-xs text-muted-foreground">{zoomPercent}%</span>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => zoomAtTargetCenter(zoomStep)}
          data-zoom-control="true"
        >
          <Plus className="h-4 w-4" />
          Zoom In
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => zoomAtTargetCenter(1 / zoomStep)}
          data-zoom-control="true"
        >
          <Minus className="h-4 w-4" />
          Zoom Out
        </Button>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={resetTransform}
          data-zoom-control="true"
        >
          <RotateCcw className="h-4 w-4" />
          Reset
        </Button>
      </div>
      <div
        ref={viewportRef}
        className={cn(
          "relative flex-1 overflow-hidden rounded-md border touch-none",
          isPanning ? "cursor-grabbing" : "cursor-grab",
        )}
        onWheelCapture={(event) => {
          if (!getZoomTarget()) return;
          if (requireModifierForWheelZoom && !event.ctrlKey && !event.metaKey) {
            return;
          }
          event.preventDefault();
          event.stopPropagation();
          const axisDelta =
            Math.abs(event.deltaY) >= Math.abs(event.deltaX) ? event.deltaY : event.deltaX;
          wheelDeltaRef.current += axisDelta;
          lastWheelEventRef.current = event.nativeEvent;
          if (wheelRafRef.current === null) {
            wheelRafRef.current = requestAnimationFrame(flushWheel);
          }
        }}
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          const target = event.target;
          if (target instanceof HTMLElement && target.closest("[data-zoom-control='true']")) return;
          if (
            target instanceof HTMLElement &&
            target.closest("button, a, input, textarea, select, [role='button']")
          ) {
            return;
          }
          event.preventDefault();
          dragRef.current = {
            pointerId: event.pointerId,
            startClientX: event.clientX,
            startClientY: event.clientY,
            startX: transformRef.current.x,
            startY: transformRef.current.y,
          };
          event.currentTarget.setPointerCapture(event.pointerId);
          setIsPanning(true);
        }}
        onPointerMove={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          event.preventDefault();
          const deltaX = event.clientX - drag.startClientX;
          const deltaY = event.clientY - drag.startClientY;
          pendingPanRef.current = {
            x: drag.startX + deltaX,
            y: drag.startY + deltaY,
          };
          if (panRafRef.current === null) {
            panRafRef.current = requestAnimationFrame(flushPan);
          }
        }}
        onPointerUp={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          if (panRafRef.current !== null) {
            cancelAnimationFrame(panRafRef.current);
            panRafRef.current = null;
          }
          commitPendingPan();
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
          setIsPanning(false);
        }}
        onPointerCancel={(event) => {
          const drag = dragRef.current;
          if (!drag || drag.pointerId !== event.pointerId) return;
          if (panRafRef.current !== null) {
            cancelAnimationFrame(panRafRef.current);
            panRafRef.current = null;
          }
          pendingPanRef.current = null;
          dragRef.current = null;
          event.currentTarget.releasePointerCapture(event.pointerId);
          setIsPanning(false);
        }}
      >
        <div
          className="h-full w-full overflow-hidden"
          style={isPanning ? { pointerEvents: "none" } : undefined}
        >
          {children}
        </div>
      </div>
    </div>
  );
});

export default TreeZoomPane;
