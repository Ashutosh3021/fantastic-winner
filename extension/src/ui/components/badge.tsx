import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

/**
 * Badge.
 *
 * A pill is the honest shape for a tag or a status, so this is the one place
 * one is allowed. Tags carry meaning (`recommended`, `mistake_type`), never
 * decoration, so there is no `.badge` variant for arbitrary emphasis.
 */
const badgeVariants = cva(
  [
    "inline-flex max-w-full items-center gap-1 rounded-full border",
    "px-2 py-0.5 text-[11px] leading-4 font-medium",
    "transition-colors duration-[var(--duration-micro)]",
    "[&_svg]:size-3 [&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary:
          "border-transparent bg-primary-subtle text-primary-subtle-foreground",
        neutral: "border-border bg-muted text-muted-foreground",
        outline: "border-border-strong bg-transparent text-muted-foreground",
        success:
          "border-transparent bg-success-subtle text-success-subtle-foreground",
        warning:
          "border-transparent bg-warning-subtle text-warning-subtle-foreground",
        danger:
          "border-transparent bg-destructive-subtle text-destructive-subtle-foreground",
      },
    },
    defaultVariants: { variant: "neutral" },
  },
);

export type BadgeProps = React.ComponentProps<"span"> & VariantProps<typeof badgeVariants>;

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { badgeVariants };