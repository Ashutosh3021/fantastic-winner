import * as SelectPrimitive from "@radix-ui/react-select";
import { createContext, useContext, useRef, useState } from "react";

import { AppIcon, ChevronDownIcon, CheckmarkCircle02Icon } from "../icons";
import { cn } from "../../lib/utils";

type SelectProps = React.ComponentProps<typeof SelectPrimitive.Root>;

/** Timestamp of the last item selection, shared with `SelectItem`. */
const SelectionMarker = createContext<{ at: number } | null>(null);

/**
 * `Select` with a short close guard.
 *
 * Chrome sizes an extension popup to its content, and mounting a portaled menu
 * can resize/blur the window for a frame. Radix reads that as focus moving
 * outside and closes the list the instant it opens (a visible flash). Suppress
 * that synthetic close only; choosing an item, pressing Escape, or clicking
 * outside after the guard window still closes normally.
 */
export function Select({ onOpenChange, ...props }: SelectProps) {
  const [open, setOpen] = useState(false);
  const openedAt = useRef(0);
  const selection = useRef({ at: 0 });

  function handleOpenChange(next: boolean) {
    if (next) {
      openedAt.current = Date.now();
      setOpen(true);
      onOpenChange?.(true);
      return;
    }

    const now = Date.now();
    const bySelection = now - selection.current.at < 500;
    if (!bySelection && now - openedAt.current < 400) return;

    setOpen(false);
    onOpenChange?.(false);
  }

  return (
    <SelectionMarker.Provider value={selection.current}>
      <SelectPrimitive.Root {...props} open={open} onOpenChange={handleOpenChange} />
    </SelectionMarker.Provider>
  );
}

export const SelectGroup = SelectPrimitive.Group;

/**
 * Deliberately no `SelectValue` re-export.
 *
 * `SelectValue` displays the selection by letting each `ItemText` portal itself
 * into the trigger — and items only exist while the list is open. That makes a
 * freshly-mounted controlled select render an *empty* trigger until the learner
 * has opened that dropdown once. Passing children to `SelectValue` instead
 * double-renders the label once the portal takes over.
 *
 * Callers therefore render the label directly inside `SelectTrigger`. It is
 * always correct on first paint, and the button's accessible name comes from
 * that same text.
 */

export function SelectTrigger({
  className,
  children,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Trigger>) {
  return (
    <SelectPrimitive.Trigger
      className={cn(
        "flex h-9 w-full cursor-pointer items-center justify-between gap-2 rounded-md border border-input bg-card px-3 text-sm",
        "transition-[border-color,box-shadow] duration-[var(--duration-micro)] ease-out",
        "hover:border-border-strong",
        "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
        "disabled:cursor-not-allowed disabled:opacity-50",
        "data-[placeholder]:text-muted-foreground",
        "[&>span]:truncate",
        className,
      )}
      {...props}
    >
      {children}
      <SelectPrimitive.Icon asChild>
        <AppIcon
          icon={ChevronDownIcon}
          size={16}
          className="shrink-0 text-muted-foreground transition-transform duration-[var(--duration-micro)] data-[state=open]:rotate-180"
        />
      </SelectPrimitive.Icon>
    </SelectPrimitive.Trigger>
  );
}

export function SelectContent({
  className,
  children,
  position = "popper",
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Content>) {
  return (
    <SelectPrimitive.Portal>
      <SelectPrimitive.Content
        position={position}
        sideOffset={4}
        className={cn(
          "relative z-50 max-h-72 min-w-[var(--radix-select-trigger-width)] overflow-hidden",
          "rounded-lg border border-border bg-popover text-popover-foreground shadow-e2",
          "data-[state=open]:animate-[cm-pop_--duration-ui_cubic-bezier(0.16,1,0.3,1)]",
          "data-[state=closed]:animate-[cm-unpop_--duration-micro_ease-out]",
          className,
        )}
        {...props}
      >
        <SelectPrimitive.Viewport className="p-1">{children}</SelectPrimitive.Viewport>
      </SelectPrimitive.Content>
    </SelectPrimitive.Portal>
  );
}

export function SelectItem({
  className,
  children,
  onSelect,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Item>) {
  const selection = useContext(SelectionMarker);

  return (
    <SelectPrimitive.Item
      onSelect={(event) => {
        if (selection) selection.at = Date.now();
        onSelect?.(event);
      }}
      className={cn(
        "relative flex w-full cursor-pointer items-center gap-2 rounded-md py-1.5 pr-7 pl-2.5 text-sm",
        "outline-none select-none",
        "data-[highlighted]:bg-accent data-[highlighted]:text-accent-foreground",
        "data-[disabled]:pointer-events-none data-[disabled]:opacity-50",
        className,
      )}
      {...props}
    >
      <SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText>
      <span className="absolute right-2 flex size-4 items-center justify-center">
        <SelectPrimitive.ItemIndicator>
          <AppIcon icon={CheckmarkCircle02Icon} size={16} className="text-primary" />
        </SelectPrimitive.ItemIndicator>
      </span>
    </SelectPrimitive.Item>
  );
}

export function SelectLabel({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Label>) {
  return (
    <SelectPrimitive.Label
      className={cn(
        "px-2.5 py-1.5 text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase",
        className,
      )}
      {...props}
    />
  );
}

export function SelectSeparator({
  className,
  ...props
}: React.ComponentProps<typeof SelectPrimitive.Separator>) {
  return (
    <SelectPrimitive.Separator
      className={cn("-mx-1 my-1 h-px bg-border", className)}
      {...props}
    />
  );
}