import { cn } from "../../lib/utils";

/**
 * Skeleton.
 *
 * Use these when the *shape* of the content is known. Anything that arrives
 * without a known structure gets a sentence instead — a row of grey bars is a
 * promise about content the renderer does not have.
 */
export function Skeleton({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      aria-hidden
      className={cn("animate-pulse rounded-md bg-muted", className)}
      {...props}
    />
  );
}

/** Three stacked text lines, the most common placeholder in this product. */
export function SkeletonLines({
  lines = 3,
  className,
}: {
  lines?: number;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-2", className)}>
      {Array.from({ length: lines }, (_, i) => (
        <Skeleton
          key={i}
          className={i === lines - 1 ? "h-3 w-2/3" : i % 2 === 0 ? "h-3 w-full" : "h-3 w-5/6"}
        />
      ))}
    </div>
  );
}