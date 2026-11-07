import { useEffect, useState } from "react";

import { Button } from "../components/button";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "../components/collapsible";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../components/card";
import { SkeletonLines } from "../components/skeleton";
import { AppIcon, ChevronDownIcon, ClipboardListIcon, CodeIcon } from "../icons";
import { cn } from "../../lib/utils";
import type { ChecklistResponse, Language } from "../../schemas";
import { strings } from "../../i18n/strings";
import { overlayStateStore, setChecklistRevealed } from "../../state/prefs";

type Props = {
  checklist: ChecklistResponse | null;
  slug: string;
  language: Language;
  loading: boolean;
  onOpenAnalysis: () => void;
  onMarkDone: () => void;
  pending: boolean;
};

/**
 * Full-solution mode (PLAN §3 Step 5).
 *
 * The checklist is an **earned** artifact: the server only returns it after the
 * last question is passed, and here it renders **collapsed by default** so it is
 * never sitting on screen unasked. It contains prose bullets, never code (§11.2).
 *
 * The shape of the pending state is known — a title, eight or so bullets — so it
 * renders as a skeleton rather than as the word "Loading".
 */
export function ChecklistCard({
  checklist,
  slug,
  language,
  loading,
  onOpenAnalysis,
  onMarkDone,
  pending,
}: Props) {
  const t = strings(language);
  const [open, setOpenState] = useState(false);

  useEffect(() => {
    void overlayStateStore.getValue().then((state) => {
      // Reveal state belongs to the problem it was earned on. Without the slug
      // check, opening one checklist pre-opened every later problem's plan.
      const saved =
        state.checklistRevealedBySlug?.[slug] ??
        (state.lastSlug === slug && state.checklistRevealed);
      setOpenState(saved);
    });
  }, [slug]);

  function setOpen(next: boolean) {
    setOpenState(next);
    void setChecklistRevealed(slug, next);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t.allDoneHeading}</CardTitle>
        <CardDescription>{t.writeItNow}</CardDescription>
      </CardHeader>

      <CardContent>
        {loading && <SkeletonLines lines={3} />}

        {!loading && checklist && (
          <Collapsible
            open={open}
            onOpenChange={setOpen}
            className="rounded-lg border border-border"
          >
            <CollapsibleTrigger className="flex w-full cursor-pointer items-center justify-between gap-2 rounded-lg px-3 py-2.5 text-left transition-colors duration-[var(--duration-micro)] hover:bg-accent/50 focus-visible:ring-[3px] focus-visible:ring-ring/25 focus-visible:outline-none">
              <span className="flex items-center gap-2 text-xs font-medium">
                <AppIcon icon={ClipboardListIcon} size={16} className="text-muted-foreground" />
                {t.checklistCollapsed}
                <span className="font-mono text-[11px] tabular-nums text-muted-foreground">
                  {checklist.items.length}
                </span>
              </span>
              <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                {open ? "Hide" : t.revealPlan}
                <AppIcon
                  icon={ChevronDownIcon}
                  size={16}
                  className={cn(
                    "transition-transform duration-[var(--duration-ui)] ease-out",
                    open && "rotate-180",
                  )}
                />
              </span>
            </CollapsibleTrigger>

            <CollapsibleContent>
              <ol className="flex list-decimal flex-col gap-1.5 border-t border-border px-3 py-2.5 pl-7 text-sm leading-relaxed text-muted-foreground marker:text-muted-foreground/60">
                {checklist.items.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ol>
            </CollapsibleContent>
          </Collapsible>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button onClick={onOpenAnalysis} disabled={pending}>
            <AppIcon icon={CodeIcon} size={16} />
            {t.openAnalysis}
          </Button>
          <Button variant="secondary" onClick={onMarkDone} disabled={pending}>
            I finished the problem
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}