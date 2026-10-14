import * as TabsPrimitive from "@radix-ui/react-tabs";

import { cn } from "../../lib/utils";

export const Tabs = TabsPrimitive.Root;

/**
 * Tabs.
 *
 * Two shapes, both restrained. `segment` for a small closed set inside a panel
 * (the analysis window's four views); `underline` for top-level navigation where
 * the list is the page's structure and a filled pill would compete with the
 * content for attention.
 */
export function TabsList({
  className,
  variant = "segment",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.List> & { variant?: "segment" | "underline" }) {
  return (
    <TabsPrimitive.List
      className={cn(
        "flex items-center",
        variant === "segment" &&
          "inline-flex h-8 w-fit gap-0.5 rounded-md border border-border bg-muted p-0.5",
        variant === "underline" && "w-full gap-0 border-b border-border",
        className,
      )}
      {...props}
    />
  );
}

export function TabsTrigger({
  className,
  variant = "segment",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Trigger> & { variant?: "segment" | "underline" }) {
  return (
    <TabsPrimitive.Trigger
      className={cn(
        "inline-flex cursor-pointer items-center justify-center whitespace-nowrap font-medium select-none",
        "text-muted-foreground transition-colors duration-[var(--duration-micro)] ease-out",
        "hover:text-foreground",
        "focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
        "disabled:pointer-events-none disabled:opacity-50",
        "data-[state=active]:text-foreground",
        variant === "segment" && [
          "h-7 rounded-[3px] px-2.5 text-xs",
          "data-[state=active]:bg-card data-[state=active]:shadow-e1",
        ],
        variant === "underline" && [
          "h-9 flex-1 border-b-2 border-transparent px-2 text-sm",
          "-mb-px data-[state=active]:border-primary",
        ],
        className,
      )}
      {...props}
    />
  );
}

export function TabsContent({
  className,
  variant = "segment",
  ...props
}: React.ComponentProps<typeof TabsPrimitive.Content> & { variant?: "segment" | "underline" }) {
  return (
    <TabsPrimitive.Content
      className={cn(
        "focus-visible:outline-none",
        variant === "segment" ? "mt-3" : "pt-4",
        className,
      )}
      {...props}
    />
  );
}