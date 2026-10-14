import * as LabelPrimitive from "@radix-ui/react-label";

import { cn } from "../../lib/utils";

export function Label({ className, ...props }: React.ComponentProps<typeof LabelPrimitive.Root>) {
  return (
    <LabelPrimitive.Root
      className={cn(
        "text-xs leading-4 font-medium text-foreground select-none",
        "peer-disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}