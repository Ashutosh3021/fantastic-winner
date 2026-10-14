import * as CollapsiblePrimitive from "@radix-ui/react-collapsible";

import { cn } from "../../lib/utils";

export const Collapsible = CollapsiblePrimitive.Root;
export const CollapsibleTrigger = CollapsiblePrimitive.CollapsibleTrigger;

/**
 * Animates on `height` for the length of the transition only. It is the one
 * layout-animated property in the product, used because a collapsible whose
 * content simply appears reads as a glitch rather than as a disclosure — and
 * the base `prefers-reduced-motion` rule collapses it to instant.
 */
export function CollapsibleContent({
  className,
  ...props
}: React.ComponentProps<typeof CollapsiblePrimitive.CollapsibleContent>) {
  return (
    <CollapsiblePrimitive.CollapsibleContent
      className={cn(
        "overflow-hidden",
        "data-[state=closed]:animate-[cm-collapse_--duration-ui_cubic-bezier(0.16,1,0.3,1)]",
        "data-[state=open]:animate-[cm-expand_--duration-ui_cubic-bezier(0.16,1,0.3,1)]",
        className,
      )}
      {...props}
    />
  );
}