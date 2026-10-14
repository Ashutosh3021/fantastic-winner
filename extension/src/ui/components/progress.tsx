import * as ProgressPrimitive from "@radix-ui/react-progress";

import { cn } from "../../lib/utils";

/**
 * Progress.
 *
 * An unlabelled bar. Reach for `Meter` instead when the reader needs to know
 * what is being counted — this one is for things whose length is self-evident
 * from its position (how far through the question set you are).
 */
export function Progress({
  className,
  value,
  tone = "primary",
  label,
  ...props
}: React.ComponentProps<typeof ProgressPrimitive.Root> & {
  tone?: "primary" | "success" | "warning";
  label?: string;
}) {
  const clamped = Math.min(100, Math.max(0, value ?? 0));
  return (
    <ProgressPrimitive.Root
      value={clamped}
      aria-label={label}
      className={cn("relative h-1.5 w-full overflow-hidden rounded-full bg-muted", className)}
      {...props}
    >
      <ProgressPrimitive.Indicator
        className={cn(
          "size-full flex-1 transition-transform duration-[var(--duration-ui)] ease-out",
          tone === "success" && "bg-success",
          tone === "warning" && "bg-warning",
          tone === "primary" && "bg-primary",
        )}
        style={{ transform: `translateX(-${100 - clamped}%)` }}
      />
    </ProgressPrimitive.Root>
  );
}