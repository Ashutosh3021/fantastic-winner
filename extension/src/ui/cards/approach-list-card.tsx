import { Badge } from "../components/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/card";
import { Notice } from "../components/field";
import { AppIcon, ArrowRight01Icon, StarIcon } from "../icons";
import { strings } from "../../i18n/strings";
import { cn } from "../../lib/utils";
import type { Approach, Language } from "../../schemas";

type Props = {
  title: string;
  approaches: Approach[];
  recommendedFirst: string | null;
  language: Language;
  selectedApproach?: string | null;
  costPerQuestion: number;
  creditsLeft: number;
  busy: boolean;
  onChoose: (id: string) => void;
};

/**
 * Approach list (PLAN §11).
 *
 * The decision on this screen is "how do I want to think about this?", so each
 * option is a row that answers three questions in order — what it is called,
 * why it works here, what it costs to run. Brute Force always renders first;
 * confidence is never shown as a number, because it reads as false precision
 * for a beginner. It only drives order and the badge.
 *
 * The "choose" affordance is a permanently visible arrow rather than a
 * hover-only label: a hint that appears on hover is invisible to touch, to a
 * keyboard user, and to anyone reading the page at a glance.
 */
export function ApproachListCard({
  title,
  approaches,
  recommendedFirst,
  language,
  selectedApproach,
  costPerQuestion,
  creditsLeft,
  busy,
  onChoose,
}: Props) {
  const t = strings(language);
  const ordered = [...approaches].sort((a, b) => {
    if (a.id === "brute_force") return -1;
    if (b.id === "brute_force") return 1;
    return b.confidence - a.confidence;
  });

  const affordable = creditsLeft >= costPerQuestion;
  const current = selectedApproach ?? null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{t.approachesHeading}</CardDescription>
      </CardHeader>

      <CardContent>
        <ul className="flex flex-col gap-2" aria-busy={busy || undefined}>
          {ordered.map((approach) => {
            const isRecommended = approach.id === recommendedFirst;
            const isCurrent = approach.id === current;
            return (
              <li key={approach.id}>
                <button
                  type="button"
                  disabled={busy}
                  aria-current={isCurrent ? "true" : undefined}
                  onClick={() => onChoose(approach.id)}
                  className={cn(
                    "group flex w-full items-start gap-2.5 rounded-lg border p-3 text-left",
                    "transition-[border-color,background-color] duration-[var(--duration-micro)] ease-out",
                    "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none",
                    "disabled:cursor-not-allowed disabled:opacity-60",
                    isCurrent
                      ? "border-primary bg-primary-subtle"
                      : "border-border bg-card hover:border-border-strong hover:bg-accent/50",
                  )}
                >
                  <span className="flex min-w-0 flex-1 flex-col gap-1">
                    <span className="flex flex-wrap items-center gap-x-1.5 gap-y-1">
                      <span className="text-sm font-medium">{approach.name}</span>
                      {isRecommended && (
                        <Badge variant="primary">
                          <AppIcon icon={StarIcon} size={12} />
                          {t.recommended}
                        </Badge>
                      )}
                      {isCurrent && <Badge variant="outline">current</Badge>}
                      {approach.id === "brute_force" && (
                        <Badge variant="neutral">baseline</Badge>
                      )}
                    </span>

                    <span className="text-xs leading-relaxed text-muted-foreground">
                      {approach.simple_reason}
                    </span>

                    {approach.expected_complexity && (
                      <span className="font-mono text-[11px] text-muted-foreground/90">
                        {approach.expected_complexity}
                      </span>
                    )}
                  </span>

                  <AppIcon
                    icon={ArrowRight01Icon}
                    size={16}
                    className={cn(
                      "mt-0.5 shrink-0 transition-[color,transform] duration-[var(--duration-micro)] ease-out",
                      isCurrent
                        ? "text-primary"
                        : "text-muted-foreground/60 group-hover:translate-x-0.5 group-hover:text-foreground group-focus-visible:text-foreground",
                    )}
                  />
                </button>
              </li>
            );
          })}
        </ul>

        {current ? (
          <p className="text-[11px] leading-relaxed text-muted-foreground">
            {t.switchResets}
          </p>
        ) : affordable ? (
          <div className="flex flex-col gap-0.5">
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              {t.chooseApproach}
            </p>
            <p className="text-[11px] leading-relaxed text-muted-foreground/80">
              {t.creditCost(costPerQuestion, creditsLeft)}
            </p>
          </div>
        ) : (
          <Notice tone="warning">
            You need at least {costPerQuestion} question credits to start the questions.{" "}
            {t.creditsExhaustedBody}
          </Notice>
        )}
      </CardContent>
    </Card>
  );
}