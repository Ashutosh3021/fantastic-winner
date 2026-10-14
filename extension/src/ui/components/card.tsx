import * as React from "react";

import { cn } from "../../lib/utils";

/**
 * Card.
 *
 * A card groups one thing. Inside the overlay the panel already supplies the
 * border, the radius and the shadow, so a card here contributes a second border
 * and nothing else — that is the signal that it is a *region* rather than a
 * floating object, and it is what keeps the panel from turning into card soup.
 *
 * Padding lives on the card itself and the parts are spaced with `gap`. That
 * removes the usual `CardContent className="pt-4"` footgun entirely: there is
 * no padding to override when there is no header.
 */
export function Card({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-col gap-3 rounded-xl border border-border bg-card p-4 text-card-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function CardHeader({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-1", className)} {...props} />;
}

export function CardTitle({ className, ...props }: React.ComponentProps<"h3">) {
  return (
    <h3
      className={cn("text-sm leading-5 font-semibold tracking-[-0.01em]", className)}
      {...props}
    />
  );
}

export function CardDescription({ className, ...props }: React.ComponentProps<"p">) {
  return (
    <p className={cn("text-sm leading-relaxed text-muted-foreground", className)} {...props} />
  );
}

export function CardContent({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("flex flex-col gap-3", className)} {...props} />;
}

/**
 * A quiet bordered region for content that sits *inside* a card without
 * deserving its own card. Uses the muted surface so nesting reads without
 * another shadow.
 */
export function CardRegion({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border border-border bg-muted/50 p-3",
        className,
      )}
      {...props}
    />
  );
}