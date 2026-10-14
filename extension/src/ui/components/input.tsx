import * as React from "react";

import { cn } from "../../lib/utils";

const controlBase = [
  "w-full rounded-md border border-input bg-card text-sm text-foreground",
  "placeholder:text-muted-foreground",
  "transition-[border-color,box-shadow,background-color] duration-[var(--duration-micro)] ease-out",
  "hover:border-border-strong",
  "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
  "disabled:cursor-not-allowed disabled:opacity-50",
  "aria-[invalid=true]:border-destructive aria-[invalid=true]:ring-destructive/20",
].join(" ");

export function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      className={cn(controlBase, "h-9 px-3 py-1", className)}
      {...props}
    />
  );
}

export function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      className={cn(controlBase, "min-h-20 resize-y px-3 py-2 leading-relaxed", className)}
      {...props}
    />
  );
}