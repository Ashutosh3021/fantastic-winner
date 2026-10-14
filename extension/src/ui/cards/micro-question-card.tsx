import { useMemo } from "react";

import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Card, CardContent, CardHeader, CardRegion, CardTitle } from "../components/card";
import { Checkbox } from "../components/checkbox";
import { Diagram } from "../components/diagram";
import { Field } from "../components/field";
import { Input, Textarea } from "../components/input";
import { Progress } from "../components/progress";
import { RadioCard, RadioGroup } from "../components/radio-card";
import {
  AppIcon,
  CancelCircleIcon,
  CheckmarkCircle02Icon,
  EyeIcon,
  HelpCircleIcon,
  LightbulbIcon,
} from "../icons";
import { cn } from "../../lib/utils";
import { OrderSteps } from "./order-steps";
import type { AnswerResponse, CurrentQuestion, Language } from "../../schemas";
import { strings } from "../../i18n/strings";

type Props = {
  question: CurrentQuestion;
  language: Language;
  feedback: AnswerResponse | null;
  hint: { text: string; level: number } | null;
  busy: boolean;
  draftText: string;
  draftChoices: number[];
  draftOrder: number[];
  onDraft: (patch: { text?: string; choiceIndexes?: number[]; order?: number[] }) => void;
  onSubmit: () => void;
  onHint: () => void;
  onReveal: () => void;
};

const VERDICT_STYLE = {
  correct: {
    icon: CheckmarkCircle02Icon,
    region: "border-success/30 bg-success-subtle",
    titleClass: "text-success-subtle-foreground",
  },
  partial: {
    icon: HelpCircleIcon,
    region: "border-warning/30 bg-warning-subtle",
    titleClass: "text-warning-subtle-foreground",
  },
  incorrect: {
    icon: CancelCircleIcon,
    region: "border-destructive/30 bg-destructive-subtle",
    titleClass: "text-destructive-subtle-foreground",
  },
} as const;

/**
 * Micro-question card (§10, PLAN §11).
 *
 * The server sends one question at a time and never the rubric, the step
 * explanation, or the next question until this one is passed. The card can only
 * render what it was given.
 *
 * Every answer type is a real form control inside a `fieldset`, so "pick one",
 * "pick all", and "put these in order" are announced as groups rather than as a
 * stack of unlabelled divs.
 */
export function MicroQuestionCard({
  question,
  language,
  feedback,
  hint,
  busy,
  draftText,
  draftChoices,
  draftOrder,
  onDraft,
  onSubmit,
  onHint,
  onReveal,
}: Props) {
  const t = strings(language);
  const answered = feedback?.verdict === "correct";

  const stepItems = useMemo(
    () => (question.choices ?? []).map((text, index) => ({ id: String(index), text })),
    [question.choices],
  );

  /** The learner's current ordering; defaults to the order the steps arrived in. */
  const orderedSteps = useMemo(
    () => (draftOrder.length > 0 ? draftOrder : stepItems.map((step) => Number(step.id))),
    [draftOrder, stepItems],
  );

  const canSubmit = useMemo(() => {
    switch (question.answer_type) {
      case "single_choice":
      case "multi_choice":
        return draftChoices.length > 0;
      case "order_steps":
        return orderedSteps.length === (question.choices?.length ?? 0);
      case "fill_blank":
      case "predict_state":
      case "short_text":
        return draftText.trim().length > 0;
    }
  }, [question.answer_type, question.choices, draftChoices, draftText, orderedSteps]);

  const remaining = Math.max(0, question.total - question.index);
  const verdict = feedback ? VERDICT_STYLE[feedback.verdict] : null;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-3">
          <CardTitle className="shrink-0 text-xs font-medium text-muted-foreground">
            {t.microQuestionOf(question.index, question.total)}
          </CardTitle>
          <Progress
            className="flex-1"
            value={(question.index / question.total) * 100}
            label="Questions answered"
          />
          <span className="shrink-0 font-mono text-[11px] tabular-nums text-muted-foreground">
            {remaining} left
          </span>
        </div>
      </CardHeader>

      <CardContent>
        <p className="text-[15px] leading-snug font-medium">{question.prompt}</p>

        {question.diagram && <Diagram spec={question.diagram} />}

        <AnswerInput
          question={question}
          labels={t}
          draftText={draftText}
          draftChoices={draftChoices}
          orderedSteps={orderedSteps}
          steps={stepItems}
          disabled={busy}
          onDraft={onDraft}
        />

        {feedback && verdict && (
          <div
            className={cn("flex flex-col gap-1 rounded-lg border p-3", verdict.region)}
            role="status"
          >
            <p
              className={cn(
                "flex items-center gap-1.5 text-xs font-semibold",
                verdict.titleClass,
              )}
            >
              <AppIcon icon={verdict.icon} size={14} />
              {feedback.verdict === "correct"
                ? "That's it."
                : feedback.verdict === "partial"
                  ? "Partly there."
                  : "Not yet."}
            </p>
            <p className="text-sm leading-relaxed text-foreground/90">{feedback.feedback}</p>
          </div>
        )}

        {hint && (
          <CardRegion>
            <p className="flex items-center gap-1.5 text-xs font-medium">
              <AppIcon icon={LightbulbIcon} size={14} className="text-warning" />
              Hint {hint.level} of 3
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">{hint.text}</p>
          </CardRegion>
        )}

        {question.revealed && question.step_explanation && (
          <CardRegion>
            <p className="flex items-center gap-1.5 text-xs font-medium">
              <AppIcon icon={EyeIcon} size={14} />
              This step, in words
            </p>
            <p className="text-sm leading-relaxed text-muted-foreground">
              {question.step_explanation}
            </p>
          </CardRegion>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button onClick={onSubmit} disabled={busy || !canSubmit || answered} loading={busy}>
            {answered ? t.nextQuestion : t.checkUnderstanding}
          </Button>

          {question.hints_available && !answered && (
            <Button variant="secondary" onClick={onHint} disabled={busy}>
              <AppIcon icon={LightbulbIcon} size={16} />
              {t.needHint(question.hints_used, 3)}
            </Button>
          )}

          {!answered && question.attempts >= 3 && !question.revealed && (
            <Button variant="ghost" size="sm" onClick={onReveal} disabled={busy}>
              <AppIcon icon={EyeIcon} size={14} />
              {t.showMeThisStep}
            </Button>
          )}

          {feedback?.mistake_type && (
            <Badge variant="outline" className="ml-auto">
              {feedback.mistake_type.replace(/_/g, " ")}
            </Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

type InputProps = {
  question: CurrentQuestion;
  labels: Pick<ReturnType<typeof strings>, "yourAnswer">;
  draftText: string;
  draftChoices: number[];
  orderedSteps: number[];
  steps: { id: string; text: string }[];
  disabled: boolean;
  onDraft: Props["onDraft"];
};

/** Group label for an answer set. `<legend>` so screen readers announce a name. */
function ChoiceGroup({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="flex flex-col gap-1.5">
      <legend className="mb-1.5 text-xs font-medium text-foreground">{label}</legend>
      {children}
    </fieldset>
  );
}

function AnswerInput({
  question,
  labels,
  draftText,
  draftChoices,
  orderedSteps,
  steps,
  disabled,
  onDraft,
}: InputProps) {
  switch (question.answer_type) {
    case "single_choice":
      return (
        <ChoiceGroup label="Pick one">
          <RadioGroup
            value={draftChoices[0] !== undefined ? String(draftChoices[0]) : ""}
            onValueChange={(value) => onDraft({ choiceIndexes: [Number(value)] })}
            aria-label={question.prompt}
          >
            {(question.choices ?? []).map((choice, index) => (
              <RadioCard key={index} value={String(index)} disabled={disabled}>
                {choice}
              </RadioCard>
            ))}
          </RadioGroup>
        </ChoiceGroup>
      );

    case "multi_choice":
      return (
        <ChoiceGroup label="Pick all that apply">
          <div className="flex flex-col gap-2">
            {(question.choices ?? []).map((choice, index) => {
              const id = `q${question.index}-c${index}`;
              const selected = draftChoices.includes(index);
              return (
                <label
                  key={index}
                  htmlFor={id}
                  className={cn(
                    "flex cursor-pointer items-start gap-2.5 rounded-lg border p-3 text-sm leading-snug",
                    "transition-[border-color,background-color] duration-[var(--duration-micro)] ease-out",
                    selected
                      ? "border-primary bg-primary-subtle"
                      : "border-border bg-card hover:border-border-strong hover:bg-accent/50",
                  )}
                >
                  <Checkbox
                    id={id}
                    className="mt-px"
                    checked={selected}
                    disabled={disabled}
                    onCheckedChange={() =>
                      onDraft({
                        choiceIndexes: selected
                          ? draftChoices.filter((i) => i !== index)
                          : [...draftChoices, index],
                      })
                    }
                  />
                  <span className="min-w-0">{choice}</span>
                </label>
              );
            })}
          </div>
        </ChoiceGroup>
      );

    case "order_steps":
      return (
        <ChoiceGroup label="Put these steps in the right order">
          <OrderSteps
            steps={steps}
            orderedSteps={orderedSteps}
            disabled={disabled}
            onChange={(order) => onDraft({ order })}
          />
        </ChoiceGroup>
      );

    case "fill_blank":
      return (
        <Field label={labels.yourAnswer} hint="One word or phrase is enough.">
          <Input
            value={draftText}
            disabled={disabled}
            placeholder="Type the missing word or phrase"
            onChange={(event) => onDraft({ text: event.target.value })}
          />
        </Field>
      );

    case "predict_state":
    case "short_text":
    default:
      return (
        <Field
          label={labels.yourAnswer}
          hint="A sentence or two in your own words is enough."
        >
          <Textarea
            value={draftText}
            disabled={disabled}
            rows={3}
            placeholder="What happens here, and why?"
            onChange={(event) => onDraft({ text: event.target.value })}
          />
        </Field>
      );
  }
}