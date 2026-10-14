import { AppIcon, Alert02Icon, Timer01Icon } from "../icons";
import { cn } from "../../lib/utils";

/**
 * Meter.
 *
 * A labelled consumption bar. Exists instead of a bare `Progress` wherever the
 * reader needs to know *what* is being counted and *how much is left* — a bar on
 * its own is a shape, not a number.
 */
export function Meter({
  label,
  used,
  total,
  resetLabel,
  tone = "primary",
  className,
}: {
  label: string;
  used: number;
  total: number;
  resetLabel?: string;
  tone?: "primary" | "warning" | "danger";
  className?: string;
}) {
  const safeTotal = Math.max(0, total);
  const ratio = safeTotal === 0 ? 0 : Math.min(1, used / safeTotal);
  const left = Math.max(0, safeTotal - used);
  const percent = Math.round(ratio * 100);
  const low = left > 0 && left <= Math.max(1, Math.ceil(safeTotal * 0.1));
  const resolved = tone === "primary" && low ? "warning" : tone;

  const barColor =
    resolved === "danger"
      ? "bg-destructive"
      : resolved === "warning"
        ? "bg-warning"
        : "bg-primary";

  return (
    <div className={cn("flex flex-col gap-1.5", className)}>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-medium tracking-[0.06em] text-muted-foreground uppercase">
          {label}
        </span>
        <span className="font-mono text-xs tabular-nums text-foreground">
          {left}
          <span className="text-muted-foreground"> / {safeTotal} left</span>
        </span>
      </div>

      <div
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={safeTotal}
        aria-valuenow={used}
        aria-valuetext={`${percent}% used, ${left} of ${safeTotal} remaining`}
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full transition-[width] duration-[var(--duration-ui)] ease-out", barColor)}
          style={{ width: `${percent}%` }}
        />
      </div>

      {(low || resetLabel) && (
        <p
          className={cn(
            "flex items-center gap-1.5 text-[11px] leading-relaxed",
            low ? "text-warning-subtle-foreground" : "text-muted-foreground",
          )}
        >
          {low ? (
            <AppIcon icon={Alert02Icon} size={12} className="shrink-0" />
          ) : (
            <AppIcon icon={Timer01Icon} size={12} className="shrink-0" />
          )}
          {low ? `Only ${left} left.` : resetLabel}
        </p>
      )}
    </div>
  );
}