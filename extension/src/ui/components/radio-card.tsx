import * as RadioGroupPrimitive from "@radix-ui/react-radio-group";

import { AppIcon, Tick02Icon } from "../icons";
import { cn } from "../../lib/utils";

export function RadioGroup({
  className,
  ...props
}: React.ComponentProps<typeof RadioGroupPrimitive.Root>) {
  return <RadioGroupPrimitive.Root className={cn("grid gap-2", className)} {...props} />;
}

/**
 * A radio option that looks like the answer it holds, not like a form control
 * with a circle glued to it. The whole surface is the target, the ring is the
 * indicator, and selection is carried by border, background *and* the tick —
 * never by colour alone.
 */
export function RadioCard({
  value,
  children,
  disabled,
  className,
}: {
  value: string;
  children: React.ReactNode;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <RadioGroupPrimitive.Item
      value={value}
      disabled={disabled}
      className={cn(
        "group flex cursor-pointer items-start gap-2.5 rounded-lg border border-border bg-card p-3 text-left text-sm",
        "leading-snug transition-[border-color,background-color] duration-[var(--duration-micro)] ease-out",
        "hover:border-border-strong hover:bg-accent/50",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
        "disabled:cursor-not-allowed disabled:opacity-55",
        "data-[state=checked]:border-primary data-[state=checked]:bg-primary-subtle",
        className,
      )}
    >
      <span
        className={cn(
          "mt-px flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors duration-[var(--duration-micro)]",
          "border-border-strong text-transparent",
          "group-data-[state=checked]:border-primary group-data-[state=checked]:bg-primary",
          "group-data-[state=checked]:text-primary-foreground",
        )}
      >
        <RadioGroupPrimitive.Indicator forceMount>
          <AppIcon icon={Tick02Icon} size={10} strokeWidth={2.4} />
        </RadioGroupPrimitive.Indicator>
      </span>
      <span className="min-w-0">{children}</span>
    </RadioGroupPrimitive.Item>
  );
}