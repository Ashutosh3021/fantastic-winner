import * as DialogPrimitive from "@radix-ui/react-dialog";

import { AppIcon, Cancel01Icon } from "../icons";
import { cn } from "../../lib/utils";

export const Dialog = DialogPrimitive.Root;
export const DialogTrigger = DialogPrimitive.Trigger;
export const DialogClose = DialogPrimitive.Close;

export function DialogContent({
  className,
  children,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Content>) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay
        className={cn(
          "fixed inset-0 z-50 bg-black/45",
          "data-[state=open]:animate-[cm-fade_--duration-ui_ease-out] data-[state=closed]:animate-[cm-fade-out_--duration-micro_ease-out]",
        )}
      />
      <DialogPrimitive.Content
        className={cn(
          "fixed top-1/2 left-1/2 z-50 w-[calc(100vw-2rem)] max-w-sm -translate-x-1/2 -translate-y-1/2",
          "flex flex-col gap-4 rounded-xl border border-border bg-popover p-4 text-popover-foreground shadow-e3",
          "focus:outline-none",
          "data-[state=open]:animate-[cm-pop_--duration-panel_cubic-bezier(0.16,1,0.3,1)]",
          "data-[state=closed]:animate-[cm-unpop_--duration-ui_ease-out]",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close
          className={cn(
            "absolute top-3 right-3 inline-flex size-7 cursor-pointer items-center justify-center rounded-md",
            "text-muted-foreground transition-colors duration-[var(--duration-micro)]",
            "hover:bg-accent hover:text-accent-foreground",
            "focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
          )}
        >
          <AppIcon icon={Cancel01Icon} size={16} />
          <span className="sr-only">Close</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  );
}

export function DialogHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1.5 pr-7", className)} {...props} />;
}

export function DialogTitle({ className, ...props }: React.ComponentProps<typeof DialogPrimitive.Title>) {
  return (
    <DialogPrimitive.Title
      className={cn("text-sm leading-5 font-semibold tracking-[-0.01em]", className)}
      {...props}
    />
  );
}

export function DialogDescription({
  className,
  ...props
}: React.ComponentProps<typeof DialogPrimitive.Description>) {
  return (
    <DialogPrimitive.Description
      className={cn("text-sm leading-relaxed text-muted-foreground", className)}
      {...props}
    />
  );
}

export function DialogFooter({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-wrap justify-end gap-2", className)} {...props} />;
}