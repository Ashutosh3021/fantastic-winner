import * as CheckboxPrimitive from "@radix-ui/react-checkbox";

import { AppIcon, Tick02Icon } from "../icons";
import { cn } from "../../lib/utils";

export function Checkbox({ className, ...props }: React.ComponentProps<typeof CheckboxPrimitive.Root>) {
  return (
    <CheckboxPrimitive.Root
      className={cn(
        "peer size-4 shrink-0 cursor-pointer rounded-[3px] border border-input bg-card",
        "transition-[background-color,border-color] duration-[var(--duration-micro)] ease-out",
        "hover:border-border-strong",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "data-[state=checked]:border-primary data-[state=checked]:bg-primary",
        "data-[state=checked]:text-primary-foreground",
        className,
      )}
      {...props}
    >
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
        <AppIcon icon={Tick02Icon} size={12} strokeWidth={2.2} />
      </CheckboxPrimitive.Indicator>
    </CheckboxPrimitive.Root>
  );
}