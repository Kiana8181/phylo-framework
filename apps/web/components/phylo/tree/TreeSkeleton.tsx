// Loading placeholder matching the tree pane's real dimensions (no layout shift).
// Spec called for a shadcn `Skeleton`, but this repo has no such primitive — this
// is the lightweight equivalent (Tailwind `animate-pulse` on `bg-muted`).

function Block({ className }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-muted ${className ?? ""}`} />;
}

export default function TreeSkeleton({ height }: { height?: number | string }) {
  return (
    <div
      className="relative w-full overflow-hidden rounded border bg-background"
      style={{ height: height ?? 520 }}
      aria-busy="true"
      aria-label="Loading tree"
    >
      {/* header strip */}
      <div className="flex items-center gap-2 border-b p-3">
        <Block className="h-6 w-40" />
        <Block className="h-6 w-24" />
      </div>
      {/* large pane */}
      <div className="p-6">
        <Block className="h-[60%] min-h-[180px] w-full" />
      </div>
      {/* bottom-left minimap block */}
      <Block className="absolute bottom-4 left-4 h-20 w-32" />
      {/* bottom-right control cluster */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-2">
        <Block className="h-8 w-8" />
        <Block className="h-8 w-8" />
        <Block className="h-8 w-8" />
      </div>
    </div>
  );
}
