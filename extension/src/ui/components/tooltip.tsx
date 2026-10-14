import * as TooltipPrimitive from "@radix-ui/react-tooltip";

import { cn } from "../../lib/utils";

export const TooltipProvider = TooltipPrimitive.Provider;
export const Tooltip = TooltipPrimitive.Root;
export const TooltipTrigger = TooltipPrimitive.Trigger;

/**
 * Tooltip.
 *
 * Supplementary only. A tooltip may restate or extend a visible label; it may
 * never be the only place a piece of information exists, because a tooltip is
 * unreachable by keyboard on some platforms and invisible on touch.
 */
export function TooltipContent({
  className,
  sideOffset = 6,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 max-w-64 rounded-md border border-border bg-popover px-2 py-1",
          "text-[11px] leading-relaxed text-popover-foreground shadow-e2",
          "data-[state=delayed-open]:animate-[cm-fade_--duration-micro_ease-out]",
          className,
        )}
        {...props}
      />
    </TooltipPrimitive.Portal>
  );
}