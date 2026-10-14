import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "../../lib/utils";

/**
 * Button.
 *
 * Five variants and five sizes is the whole vocabulary. Every one of them is a
 * rectangle — nothing in this product is a pill, because a pill costs horizontal
 * room and reads as decoration, and this UI lives in a 22rem popup and a narrow
 * overlay where density is the constraint.
 */
const buttonVariants = cva(
  [
    "inline-flex shrink-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap",
    "rounded-md font-medium select-none",
    "transition-[background-color,border-color,color,box-shadow,opacity] duration-[var(--duration-micro)] ease-out",
    "disabled:pointer-events-none disabled:opacity-45",
    "aria-busy:pointer-events-none",
    "[&_svg]:shrink-0",
  ],
  {
    variants: {
      variant: {
        primary:
          "bg-primary text-primary-foreground hover:bg-primary/90 active:bg-primary/85",
        secondary:
          "border border-border-strong bg-card text-secondary-foreground hover:bg-accent active:bg-accent/80",
        outline:
          "border border-border bg-transparent text-foreground hover:bg-accent hover:text-accent-foreground active:bg-accent/80",
        ghost: "bg-transparent text-muted-foreground hover:bg-accent hover:text-accent-foreground",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-destructive/90 active:bg-destructive/85",
        link: "h-auto rounded-sm p-0 text-primary underline-offset-4 hover:underline",
      },
      size: {
        sm: "h-8 px-3 text-xs [&_svg]:size-3.5",
        default: "h-9 px-3.5 text-sm [&_svg]:size-4",
        lg: "h-10 px-4 text-sm [&_svg]:size-4",
        icon: "size-8 [&_svg]:size-4",
        "icon-lg": "size-9 [&_svg]:size-[18px]",
      },
    },
    defaultVariants: { variant: "primary", size: "default" },
  },
);

export type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
    /** Sets `aria-busy`, dims the label, and swaps in a spinner. */
    loading?: boolean;
    /** Keeps the button's width when `loading` hides the label. */
    loadingLabel?: string;
  };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  loading = false,
  loadingLabel,
  children,
  disabled,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot : "button";
  const isDisabled = disabled === true || loading;

  if (!loading) {
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        disabled={disabled}
        {...props}
      >
        {children}
      </Comp>
    );
  }

  return (
    <Comp
      className={cn(buttonVariants({ variant, size, className }))}
      disabled={isDisabled}
      aria-busy="true"
      {...props}
    >
      <Spinner />
      {loadingLabel ? <span className="sr-only">{loadingLabel}</span> : children}
    </Comp>
  );
}

/** Indeterminate progress. Used only for short, known-duration actions. */
function Spinner() {
  return (
    <span
      aria-hidden
      className="size-3.5 shrink-0 animate-spin rounded-full border-2 border-current border-t-transparent opacity-70"
    />
  );
}

export { buttonVariants };