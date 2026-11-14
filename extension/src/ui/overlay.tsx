import { useCallback, useEffect, useMemo, useState } from "react";
import { Toaster, toast } from "sonner";

import { Badge } from "./components/badge";
import { Button } from "./components/button";
import { EmptyState } from "./components/empty-state";
import { Field } from "./components/field";
import { Input, Textarea } from "./components/input";
import { ScrollArea } from "./components/scroll-area";
import { Skeleton } from "./components/skeleton";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "./components/tooltip";
import {
  AppIcon,
  ChevronDownIcon,
  ChevronUpIcon,
  Coins01Icon,
  GraduationCapIcon,
} from "./icons";
import { cn } from "../lib/utils";

import { useLearnerStore } from "../state/learner";
import { readBufferOrFallback } from "../bridge/client";
import { api } from "../state/client";
import {
  formatResetTime,
  localTimezone,
  overlayStateStore,
  patchOverlayState,
  prefsStore,
  resolveTheme,
  setPrefs,
} from "../state/prefs";
import type { Language } from "../schemas";
import { strings } from "../i18n/strings";
import { track } from "../telemetry";

import { ApproachListCard } from "./cards/approach-list-card";
import { ChecklistCard } from "./cards/checklist-card";
import { ConceptCardView } from "./cards/concept-card";
import { MicroQuestionCard } from "./cards/micro-question-card";
import { AnalysisWindow, PasteCodePanel } from "./cards/analysis-window";
import { ErrorCard } from "./cards/error-card";

const FALLBACK_MIN_PLAN_CREDITS = 3;

const STAGE_LABEL: Record<string, string> = {
  idle: "Choosing an approach",
  concept: "Reading the concept",
  questioning: "Micro-questions",
  solution: "Write it yourself",
  analyzed: "Solution analysis",
  manual: "Manual entry",
};

/** Credit chip (§16.5 UX states). Counts down to the server-provided window end. */
function UsageChip({
  used,
  limit,
  resetAt,
}: {
  used: number;
  limit: number;
  resetAt: string;
}) {
  const left = Math.max(0, limit - used);
  const [now, setNow] = useState(() => Date.now());
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 30_000);
    return () => clearInterval(timer);
  }, []);

  const t = strings("en");
  const expired = Date.parse(resetAt) <= now;
  const shown = expired ? limit : left;
  const low = left <= 3;

  return (
    <Tooltip open={open} delayDuration={0}>
      <TooltipTrigger
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition-colors duration-[var(--duration-micro)]",
          low ? "border-warning/40 bg-warning-subtle text-warning-subtle-foreground" : "border-border text-muted-foreground hover:text-foreground",
        )}
      >
        <AppIcon icon={Coins01Icon} size={12} />
        <span className="font-mono tabular-nums">
          {limit - shown}/{limit}
        </span>
        <span className="sr-only">{t.creditsUsed(limit - shown, limit)}</span>
      </TooltipTrigger>
      <TooltipContent>
        {expired ? "Your credits have reset." : t.resetsAt(formatResetTime(resetAt, localTimezone()))}
      </TooltipContent>
    </Tooltip>
  );
}

export function Overlay() {
  const store = useLearnerStore();
  const [collapsed, setCollapsedState] = useState(false);
  const [dark, setDark] = useState(false);

  const language = store.language;
  const t = strings(language);

  const setCollapsed = useCallback((next: boolean) => {
    setCollapsedState(next);
    void patchOverlayState({ collapsed: next });
  }, []);

  useEffect(() => {
    void overlayStateStore.getValue().then((state) => setCollapsedState(state.collapsed));
  }, []);

  // The toaster lives outside our shadow host, so it cannot read the host's
  // `.dark` class. Resolve the effective theme here instead of borrowing the
  // page's <html>, which may be in the opposite mode entirely.
  useEffect(() => {
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    const resolve = () => {
      void prefsStore.getValue().then((prefs) => setDark(resolveTheme(prefs.theme)));
    };
    resolve();
    media.addEventListener("change", resolve);
    return () => media.removeEventListener("change", resolve);
  }, []);

  // The server owns both the plan cost and the session cap; a hard-coded 3
  // drifted from the config as soon as either changed.
  const minPlanCredits =
    store.usage?.min_plan_credits ?? FALLBACK_MIN_PLAN_CREDITS;

  const creditsLeft = useMemo(() => {
    if (!store.usage) return minPlanCredits;
    return Math.max(
      0,
      store.usage.question_credits_limit - store.usage.question_credits_used,
    );
  }, [store.usage, minPlanCredits]);

  const run = useCallback(async (work: () => Promise<void>) => {
    try {
      await work();
    } catch {
      // Store actions already convert failures into typed errors.
    }
  }, []);

  const openAnalysis = useCallback(async () => {
    const buffer = await readBufferOrFallback();
    if (!buffer) {
      // The bridge could not reach Monaco and the textarea fallback was empty:
      // ask for a paste rather than pretending we can read the editor.
      useLearnerStore.setState({ analysisMode: "paste" });
      return;
    }
    useLearnerStore.setState({ analysisMode: "idle" });
    const editorLanguage = buffer.languageId || "python3";
    await run(() => store.loadAnalysis(buffer.code, editorLanguage, buffer.ambiguous));
  }, [run, store]);

  useEffect(() => {
    if (store.notice) {
      toast(store.notice);
      store.setNotice(null);
    }
  }, [store]);

  useEffect(() => {
    if (store.usage && creditsLeft <= 3 && creditsLeft > 0) {
      track("credits_exhausted_seen", { left: creditsLeft });
    }
  }, [store.usage, creditsLeft]);

  const busy = store.pending !== "none";
  const extracting = store.pending === "extract";

  return (
    <TooltipProvider delayDuration={200}>
      <aside
        aria-label={t.brand}
        className="cm-rise flex w-[22rem] flex-col overflow-hidden rounded-xl border border-border bg-background text-foreground shadow-e3"
      >
        <header className="flex h-10 shrink-0 items-center gap-2 border-b border-border bg-card px-3">
          <AppIcon icon={GraduationCapIcon} size={16} className="shrink-0 text-primary" />
          <span className="text-xs font-semibold tracking-[-0.01em]">{t.brand}</span>

          {store.usage && (
            <span className="ml-1">
              <UsageChip
                used={store.usage.question_credits_used}
                limit={store.usage.question_credits_limit}
                resetAt={store.usage.window_end}
              />
            </span>
          )}

          <span className="flex-1" />

          <Button
            variant="ghost"
            size="icon"
            aria-label={collapsed ? `Expand ${t.brand}` : `Collapse ${t.brand}`}
            aria-expanded={!collapsed}
            onClick={() => setCollapsed(!collapsed)}
          >
            <AppIcon icon={collapsed ? ChevronUpIcon : ChevronDownIcon} size={16} />
          </Button>
        </header>

        {!collapsed && (
          <>
            <div className="relative shrink-0">
              {busy && (
                <div
                  role="status"
                  aria-label="Working"
                  className="cm-busy-bar absolute inset-x-0 top-0 h-0.5 origin-left overflow-hidden bg-primary/15"
                >
                  <div className="h-full w-1/3 animate-[cm-indeterminate_2s_cubic-bezier(0.4,0,0.2,1)_infinite] bg-primary" />
                </div>
              )}
              <span className="sr-only" aria-live="polite">
                {busy ? t.busyBody : ""}
              </span>

              <ScrollArea
                type="auto"
                className="min-h-64"
                viewportClassName="max-h-[70vh] p-3"
              >
                <div className="flex flex-col gap-3">
                  {store.error && (
                    <ErrorCard error={store.error} onRetry={() => void run(() => store.loadApproaches())} />
                  )}

                  {!store.problem && store.stage !== "manual" && extracting && (
                    <div className="flex flex-col gap-2.5" aria-hidden>
                      <Skeleton className="h-3.5 w-40" />
                      <Skeleton className="h-9 w-full" />
                      <Skeleton className="h-9 w-full" />
                      <Skeleton className="h-9 w-full" />
                    </div>
                  )}

                  {!store.problem && store.stage !== "manual" && !extracting && (
                    <EmptyState
                      size="md"
                      icon={GraduationCapIcon}
                      title="No problem on this page"
                      description="Open a LeetCode problem and CodeMentor picks it up automatically."
                    />
                  )}

                  {store.stage === "manual" && <ManualPaste language={language} />}

                  {(store.stage === "idle" || store.stage === "approaches") &&
                    store.problem && (
                      <ApproachListCard
                        title={store.problem.title}
                        approaches={store.approaches}
                        recommendedFirst={store.recommendedFirst}
                        language={language}
                        costPerQuestion={minPlanCredits}
                        creditsLeft={creditsLeft}
                        busy={busy}
                        onChoose={(id) => void run(() => store.chooseApproach(id))}
                      />
                    )}

                  {store.stage === "concept" && store.concept && (
                    <>
                      <ApproachListCard
                        title={store.problem?.title ?? ""}
                        approaches={store.approaches}
                        recommendedFirst={store.recommendedFirst}
                        language={language}
                        selectedApproach={store.session?.selected_approach ?? null}
                        costPerQuestion={minPlanCredits}
                        creditsLeft={creditsLeft}
                        busy={busy}
                        onChoose={(id) => void run(() => store.switchApproach(id))}
                      />
                      <ConceptCardView
                        card={store.concept}
                        language={language}
                        simplifiedLevel={store.simplifiedLevel}
                        simplifiedText={store.simplifiedText}
                        simplifiedWhy={store.simplifiedWhy}
                        canAfford={creditsLeft >= minPlanCredits}
                        busy={busy}
                        onSimplify={() =>
                          void run(async () => {
                            await store.loadConcept(true);
                          })
                        }
                        onStart={() => void run(() => store.startQuestions())}
                      />
                    </>
                  )}

                  {(store.stage === "questioning" || store.stage === "solution") &&
                    store.question && (
                      <MicroQuestionCard
                        question={store.question}
                        language={language}
                        feedback={store.feedback}
                        hint={store.hint ? { text: store.hint.text, level: store.hint.level } : null}
                        busy={busy}
                        draftText={store.draft.text}
                        draftChoices={store.draft.choiceIndexes}
                        draftOrder={store.draft.order}
                        onDraft={store.setDraft}
                        onSubmit={() => void run(() => store.submitAnswer())}
                        onHint={() => void run(() => store.requestHint())}
                        onReveal={() => void run(() => store.revealStep())}
                      />
                    )}

                  {store.stage === "solution" && (
                    <ChecklistCard
                      checklist={store.checklist}
                      slug={store.problem?.slug ?? ""}
                      language={language}
                      loading={store.pending === "checklist"}
                      pending={busy}
                      onOpenAnalysis={() => void openAnalysis()}
                      onMarkDone={() => void run(() => store.completeSession())}
                    />
                  )}

                  {store.stage === "analyzed" && store.analysis && (
                    <AnalysisWindow
                      analysis={store.analysis}
                      pending={store.pending === "analysis"}
                      ambiguous={store.analysisAmbiguous}
                      onAnalyze={() => void openAnalysis()}
                    />
                  )}

                  {store.stage === "solution" && store.analysisMode === "paste" && (
                    <PasteCodePanel
                      busy={store.pending === "analysis"}
                      onAnalyze={(code, editorLanguage) =>
                        void run(() => store.loadAnalysis(code, editorLanguage, false))
                      }
                    />
                  )}

                  {store.extractionNote && (
                    <p className="text-[11px] leading-relaxed text-muted-foreground">
                      {store.extractionNote}
                    </p>
                  )}
                </div>
              </ScrollArea>
            </div>

            <footer className="flex h-8 shrink-0 items-center gap-2 border-t border-border bg-card px-3">
              <span className="truncate text-[11px] text-muted-foreground">
                {STAGE_LABEL[store.stage] ?? store.stage}
              </span>
              <span className="flex-1" />
              {store.session ? (
                <Badge variant="outline" className="max-w-[9rem] truncate">
                  {store.session.selected_approach.replace(/_/g, " ")}
                </Badge>
              ) : (
                <span className="text-[11px] text-muted-foreground/70">no session</span>
              )}
            </footer>
          </>
        )}
      </aside>

      <Toaster
        position="bottom-center"
        closeButton
        theme={dark ? "dark" : "light"}
        toastOptions={{ className: "font-sans" }}
      />
    </TooltipProvider>
  );
}

/** Rung 4 of the ladder: the learner pastes the statement by hand. */
function ManualPaste({ language }: { language: Language }) {
  const t = strings(language);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [slug, setSlug] = useState(() => window.location.pathname.split("/problems/")[1] ?? "");

  const tooShort = text.trim().length < 40;

  async function submit() {
    setBusy(true);
    try {
      const { manualProblem } = await import("../extraction/ladder");
      const problem = await manualProblem(slug || "manual", text);
      useLearnerStore.setState({ stage: "idle", error: null });
      useLearnerStore.getState().setProblem(problem);
      await useLearnerStore.getState().loadApproaches();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-xl border border-border bg-card p-4">
      <p className="text-sm leading-relaxed">{t.manualPasteBody}</p>

      <Field label="Problem slug" hint="Taken from the page address. Edit it if it looks wrong.">
        <Input
          value={slug}
          spellCheck={false}
          onChange={(event) => setSlug(event.target.value.replace(/[^a-z0-9-]/gi, "-"))}
        />
      </Field>

      <Field
        label="Problem statement"
        error={text.length > 0 && tooShort ? "Add a little more — a few lines is enough." : undefined}
      >
        <Textarea
          className="min-h-32"
          placeholder={t.pastePlaceholder}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      </Field>

      <div className="pt-1">
        <Button onClick={() => void submit()} disabled={busy || tooShort} loading={busy} loadingLabel="Reading your problem statement">
          Continue
        </Button>
      </div>
    </div>
  );
}

/**
 * Revalidate the cached preferences against the server (§5.6).
 *
 * Called whenever the overlay opens. If `prefs_version` moved, the learner
 * changed a setting elsewhere and the cached copy is stale — we adopt the new
 * one, refresh cached content, and say so.
 */
export async function syncMe(): Promise<void> {
  const me = await api("me", {});
  const store = useLearnerStore.getState();

  const cached = await prefsStore.getValue();
  const drifted = me.data.preferences.prefs_version !== cached.prefs_version;

  store.setUsage(me.data.usage);
  store.setLanguage(me.data.preferences.language);
  await setPrefs(me.data.preferences);

  if (drifted) {
    store.setNotice("Your settings changed. CodeMentor refreshed to match.");
    // Content was rendered in the old language; re-fetch what is on screen.
    if (store.stage === "concept") void store.loadConcept();
    else void store.loadApproaches();
  }
}
