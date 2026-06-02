export function SkeletonLine({ className = "" }: { className?: string }) {
  return (
    <div
      className={`h-3 animate-pulse rounded bg-border/60 ${className}`}
    />
  );
}

export function SkeletonCard({ className = "" }: { className?: string }) {
  return (
    <div className={`rounded-lg border border-border bg-panel p-4 animate-pulse ${className}`}>
      <SkeletonLine className="w-3/4 mb-2" />
      <SkeletonLine className="w-1/2" />
    </div>
  );
}

export function SkeletonBubble() {
  return (
    <div className="flex items-start gap-2.5 animate-pulse">
      <div className="mt-0.5 h-9 w-9 shrink-0 rounded-xl bg-border/60" />
      <div className="min-w-0 flex-1 max-w-[72%]">
        <div className="mb-1 flex items-center gap-2">
          <SkeletonLine className="w-16" />
          <SkeletonLine className="w-8" />
        </div>
        <div className="rounded-2xl rounded-tl-sm border border-border bg-panel px-4 py-3 space-y-2">
          <SkeletonLine className="w-full" />
          <SkeletonLine className="w-5/6" />
          <SkeletonLine className="w-2/3" />
        </div>
      </div>
    </div>
  );
}

export function SkeletonAgentCard() {
  return (
    <div className="rounded-md border border-border p-2 animate-pulse">
      <div className="flex items-center gap-2">
        <div className="h-8 w-8 shrink-0 rounded-full bg-border/60" />
        <div className="min-w-0 flex-1 space-y-1">
          <SkeletonLine className="w-24" />
          <SkeletonLine className="w-32" />
        </div>
      </div>
    </div>
  );
}
