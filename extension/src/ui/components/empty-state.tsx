import type { IconSvgElement } from "@hugeicons/react";

import { AppIcon } from "../icons";
import { cn } from "../../lib/utils";

/**
 * Empty state.
 *
 * Three parts, in this order: what is empty, why it matters, what to do next.
 * An empty state without the third part is a dead end, and one without the first
 * reads as a bug. The illustration slot exists for exactly that reason — most of
 * these ship no icon at all.
 */
export function EmptyState({
  icon,
  title,
  description,
  action,
  size = "sm",
  className,
}: {
  icon?: IconSvgElement;
  title: string;
  description?: string;
  action?: React.ReactNode;
  size?: "sm" | "md";
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-start gap-2 rounded-lg border border-dashed border-border",
        size === "sm" ? "p-3" : "p-5",
        className,
      )}
    >
      {icon && (
        <AppIcon
          icon={icon}
          size={size === "sm" ? 16 : 24}
          className="text-muted-foreground/70"
        />
      )}
      <div className="flex flex-col gap-1">
        <p
          className={cn(
            "font-medium text-foreground",
            size === "sm" ? "text-xs" : "text-sm",
          )}
        >
          {title}
        </p>
        {description && (
          <p
            className={cn(
              "leading-relaxed text-muted-foreground",
              size === "sm" ? "text-xs" : "text-sm",
            )}
          >
            {description}
          </p>
        )}
      </div>
      {action && <div className="mt-1 flex flex-wrap gap-2">{action}</div>}
    </div>
  );
}