import type { MistakeType, Progress } from "../schemas";
import { Badge } from "../ui/components/badge";
import { Progress as ProgressBar } from "../ui/components/progress";
import { EmptyState } from "../ui/components/empty-state";
import { AppIcon, FlameIcon, Layers01Icon } from "../ui/icons";

/**
 * Progress graphs (§13.2).
 *
 * Every number arrives pre-aggregated from the projector's read models. Two
 * rules hold across all of them:
 *
 * 1. No chart leans on colour alone. Each row carries a label and a value, and
 *    each chart has an empty state that says what is missing and what fills it.
 * 2. Nothing is drawn for its own sake. The activity strip is the only graphic
 *    that encodes a value by area, because a year of days is the one case where
 *    a table would be worse.
 */

const MISTAKE_LABELS: Record<MistakeType, string> = {
  off_by_one: "Off-by-one",
  wrong_data_structure: "Wrong data structure",
  missed_edge_case: "Missed edge case",
  wrong_condition: "Wrong condition",
  misunderstood_goal: "Misunderstood the goal",
  complexity_issue: "Complexity",
  other: "Other",
};

export function MasteryBars({ progress }: { progress: Progress }) {
  if (progress.mastery.length === 0) {
    return (
      <EmptyState
        title="No concept mastery yet"
        description="Finish a problem and the concepts you touched show up here with a score."
      />
    );
  }

  return (
    <ul className="flex flex-col gap-2.5">
      {progress.mastery.map((row) => {
        const warming = row.practice_count < 3;
        return (
          <li key={row.concept} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-xs font-medium capitalize">
                {row.concept.replace(/_/g, " ")}
              </span>
              <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
                {warming ? "—" : `${Math.round(row.mastery * 100)}%`}
              </span>
            </div>
            <ProgressBar
              value={warming ? 0 : row.mastery * 100}
              tone={warming ? "warning" : row.mastery >= 0.7 ? "success" : "primary"}
              label={row.concept.replace(/_/g, " ")}
            />
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {warming
                ? `${row.practice_count} of 3 practice questions — too few to score yet`
                : `${row.practice_count} practice questions`}
            </p>
          </li>
        );
      })}
    </ul>
  );
}

export function WeaknessList({ progress }: { progress: Progress }) {
  if (progress.weaknesses.length === 0) {
    return (
      <EmptyState
        title="No repeated mistakes"
        description="When the same thing trips you twice, it appears here with the concept it belongs to."
      />
    );
  }

  const max = Math.max(...progress.weaknesses.map((w) => w.weighted_count), 1);
  const shown = progress.weaknesses.slice(0, 5);

  return (
    <ul className="flex flex-col gap-2">
      {shown.map((weak) => (
        <li key={`${weak.concept}-${weak.mistake_type}`} className="flex flex-col gap-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-xs font-medium">
              {MISTAKE_LABELS[weak.mistake_type] ?? weak.mistake_type}
            </span>
            <span className="shrink-0 text-[11px] text-muted-foreground capitalize">
              {weak.concept.replace(/_/g, " ")}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <div
              role="progressbar"
              aria-valuemin={0}
              aria-valuemax={max}
              aria-valuenow={weak.weighted_count}
              aria-label={`${MISTAKE_LABELS[weak.mistake_type] ?? weak.mistake_type}, ${weak.weighted_count} of ${max}`}
              className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted"
            >
              <div
                className="h-full rounded-full bg-destructive transition-[width] duration-[var(--duration-ui)] ease-out"
                style={{ width: `${(weak.weighted_count / max) * 100}%` }}
              />
            </div>
            <span className="w-20 shrink-0 text-right font-mono text-[11px] tabular-nums text-muted-foreground">
              ×{weak.weighted_count} · {weak.distinct_problems}p
            </span>
          </div>
        </li>
      ))}
      {progress.weaknesses.length > shown.length && (
        <li className="text-[11px] text-muted-foreground">
          +{progress.weaknesses.length - shown.length} more below the cut-off.
        </li>
      )}
    </ul>
  );
}

/**
 * Rendered as an HTML table rather than an SVG chart: the rows are short, the
 * labels must stay selectable and translatable, and seven bars do not need a
 * drawing surface.
 */
export function MistakeTypeChart({ progress }: { progress: Progress }) {
  const entries = Object.entries(progress.mistake_type_counts).filter(([, count]) => count > 0);
  if (entries.length === 0) {
    return (
      <EmptyState
        title="No mistakes logged yet"
        description="Every answer you get wrong is filed by what went wrong, not just whether it was wrong."
      />
    );
  }

  const total = entries.reduce((sum, [, count]) => sum + count, 0);
  const max = Math.max(...entries.map(([, count]) => count), 1);

  return (
    <table className="w-full text-left">
      <caption className="sr-only">Mistakes by type, out of {total} recorded</caption>
      <thead>
        <tr className="text-[11px] tracking-[0.06em] text-muted-foreground uppercase">
          <th scope="col" className="pb-1.5 font-medium">
            Type
          </th>
          <th scope="col" className="w-1/2 pb-1.5 font-medium">
            <span className="sr-only">Share</span>
          </th>
          <th scope="col" className="pb-1.5 text-right font-medium">
            Count
          </th>
        </tr>
      </thead>
      <tbody>
        {entries.map(([type, count]) => {
          const label = MISTAKE_LABELS[type as MistakeType] ?? type;
          return (
            <tr key={type}>
              <td className="py-1 pr-2 text-xs leading-snug">{label}</td>
              <td className="py-1">
                <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-full rounded-full bg-primary transition-[width] duration-[var(--duration-ui)] ease-out"
                    style={{ width: `${(count / max) * 100}%` }}
                  />
                </div>
              </td>
              <td className="py-1 text-right font-mono text-xs tabular-nums text-muted-foreground">
                {count}
              </td>
            </tr>
          );
        })}
      </tbody>
    </table>
  );
}

export function ActivityStrip({ progress }: { progress: Progress }) {
  if (progress.activity.length === 0) {
    return (
      <EmptyState
        title="No activity yet"
        description="This fills in one square for each day you pass a question."
      />
    );
  }

  const max = Math.max(...progress.activity.map((d) => d.passed_questions), 1);
  const activeDays = progress.activity.filter((d) => d.passed_questions > 0).length;

  return (
    <div className="flex flex-col gap-2">
      <svg
        viewBox="0 0 210 40"
        role="img"
        aria-label={`Questions passed per day over the last eight weeks. ${activeDays} active days, longest streak ${progress.longest_streak} days.`}
        className="w-full"
      >
        {progress.activity.map((day, i) => {
          const col = i % 14;
          const row = Math.floor(i / 14);
          const value = day.passed_questions;
          const intensity = value === 0 ? 0.08 : 0.3 + 0.7 * (value / max);
          return (
            <rect
              key={day.date}
              x={col * 15}
              y={row * 18}
              width={12}
              height={12}
              rx={2}
              fill="var(--cm-brand)"
              opacity={intensity}
            >
              <title>{`${day.date}: ${value} passed`}</title>
            </rect>
          );
        })}
      </svg>

      <p className="flex flex-wrap items-center gap-x-1.5 gap-y-0.5 text-[11px] text-muted-foreground">
        <span className="font-mono tabular-nums text-foreground">
          {progress.current_streak}
        </span>
        <span>day streak</span>
        <span aria-hidden>·</span>
        <span>longest</span>
        <span className="font-mono tabular-nums text-foreground">
          {progress.longest_streak}
        </span>
        <span aria-hidden>·</span>
        <span>level</span>
        <span className="font-mono tabular-nums text-foreground">{progress.level}</span>
        <span aria-hidden>·</span>
        <span className="font-mono tabular-nums text-foreground">{progress.xp}</span>
        <span>XP</span>
      </p>
    </div>
  );
}

export function DueReviews({ count }: { count: number }) {
  if (count === 0) {
    return (
      <EmptyState
        title="Nothing due for review"
        description="Concepts you have not practised in a while show up here."
      />
    );
  }

  return (
    <div className="flex items-center gap-2.5 rounded-lg border border-warning/30 bg-warning-subtle px-3 py-2.5">
      <AppIcon icon={Layers01Icon} size={16} className="shrink-0 text-warning-subtle-foreground" />
      <p className="min-w-0 flex-1 text-xs leading-relaxed text-warning-subtle-foreground">
        <span className="font-semibold">
          {count} concept{count === 1 ? "" : "s"}
        </span>{" "}
        ready for a second look.
      </p>
      <Badge variant="warning">{count}</Badge>
    </div>
  );
}

/**
 * Streak readout. A static icon next to a tabular number — the flame used to
 * flicker on an infinite loop, which is decoration that never stops moving and
 * reads as noise to anyone who looks at the overlay more than once.
 */
export function StreakFlame({ days }: { days: number }) {
  return (
    <span
      className="inline-flex items-center gap-1 text-xs text-muted-foreground"
      title={`${days} day streak`}
    >
      <AppIcon
        icon={FlameIcon}
        size={14}
        className={days > 0 ? "text-warning" : "text-muted-foreground/50"}
      />
      <span className="font-mono tabular-nums text-foreground">{days}</span>
      <span className="sr-only">day streak</span>
    </span>
  );
}