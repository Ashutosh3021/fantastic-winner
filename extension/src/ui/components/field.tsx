import * as React from "react";
import { cloneElement, useId } from "react";

import { Label } from "./label";
import { AppIcon, InformationCircleIcon, Alert02Icon } from "../icons";
import { cn } from "../../lib/utils";

/**
 * Field.
 *
 * Exists so no control in this product ships without a real label, a hint, or
 * an error — the three things a `<Label>` alone will not do. The control is
 * cloned with `id`, `aria-describedby` and `aria-invalid`, which means the
 * wiring cannot drift from the copy: if the hint text changes, the reference
 * follows it.
 */
export type FieldProps = {
  label: React.ReactNode;
  /** Supplementary text. Always visible — never a placeholder substitute. */
  hint?: React.ReactNode;
  error?: string;
  className?: string;
  children: React.ReactElement;
};

export function Field({ label, hint, error, className, children }: FieldProps) {
  const generated = useId();
  const childProps = children.props as { id?: string };
  const controlId = childProps.id ?? generated;
  const hintId = `${controlId}-hint`;
  const errorId = `${controlId}-error`;

  const describedBy =
    [hint ? hintId : null, error ? errorId : null].filter(Boolean).join(" ") || undefined;

  const control = cloneElement(children, {
    id: controlId,
    "aria-describedby": describedBy,
    "aria-invalid": error ? true : undefined,
  } as Partial<unknown>);

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <Label htmlFor={controlId}>{label}</Label>
      {control}
      {hint && !error && <FieldHint id={hintId}>{hint}</FieldHint>}
      {error && <FieldError id={errorId}>{error}</FieldError>}
    </div>
  );
}

export function FieldHint({
  id,
  className,
  children,
  ...props
}: React.ComponentProps<"p"> & { id?: string }) {
  return (
    <p
      id={id}
      className={cn("text-xs leading-relaxed text-muted-foreground", className)}
      {...props}
    >
      {children}
    </p>
  );
}

/** Inline advisory. `tone="warning"` is for anything the learner should act on. */
export function Notice({
  tone = "info",
  className,
  children,
  ...props
}: React.ComponentProps<"p"> & { tone?: "info" | "warning" | "danger" }) {
  const Icon = tone === "info" ? InformationCircleIcon : Alert02Icon;
  return (
    <p
      role={tone === "info" ? undefined : "status"}
      className={cn(
        "flex items-start gap-2 rounded-md border px-2.5 py-2 text-xs leading-relaxed",
        tone === "info" && "border-border bg-muted/50 text-muted-foreground",
        tone === "warning" &&
          "border-warning/30 bg-warning-subtle text-warning-subtle-foreground",
        tone === "danger" &&
          "border-destructive/30 bg-destructive-subtle text-destructive-subtle-foreground",
        className,
      )}
      {...props}
    >
      <AppIcon icon={Icon} size={14} className="mt-px" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}

function FieldError({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <p
      id={id}
      role="alert"
      className="flex items-start gap-1.5 text-xs leading-relaxed text-destructive"
    >
      <AppIcon icon={Alert02Icon} size={14} className="mt-px" />
      <span className="min-w-0">{children}</span>
    </p>
  );
}