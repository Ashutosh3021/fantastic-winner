import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Card, CardContent, CardHeader, CardRegion, CardTitle } from "../components/card";
import { Notice } from "../components/field";
import { Diagram } from "../components/diagram";
import { AppIcon, LightbulbIcon, PlayIcon } from "../icons";
import type { ConceptCard, Language } from "../../schemas";
import { strings } from "../../i18n/strings";

type Props = {
  card: ConceptCard;
  language: Language;
  simplifiedLevel: number;
  simplifiedText: string | null;
  simplifiedWhy: string | null;
  canAfford: boolean;
  busy: boolean;
  onSimplify: () => void;
  onStart: () => void;
};

/**
 * Concept card (PLAN §3 Step 3).
 *
 * The only affordances are "I still don't get it" and "Start micro-questions".
 * There is no code, and nothing here can reveal the algorithm (§11). The reading
 * comes first and the actions last, so the primary action is the one closest to
 * the end of the text the learner just read.
 */
export function ConceptCardView({
  card,
  language,
  simplifiedLevel,
  simplifiedText,
  simplifiedWhy,
  canAfford,
  busy,
  onSimplify,
  onStart,
}: Props) {
  const t = strings(language);
  const atMax = simplifiedLevel >= (card.simplified_levels_available ?? 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{card.title}</CardTitle>
      </CardHeader>

      <CardContent>
        <div className="flex flex-col gap-2 text-sm leading-relaxed">
          <p>{simplifiedText ?? card.simple_explanation}</p>
          <p className="text-muted-foreground">{simplifiedWhy ?? card.why_it_fits_this_problem}</p>
        </div>

        {card.humour_line && (
          <CardRegion className="bg-muted/60">
            <p className="text-xs leading-relaxed text-muted-foreground italic">
              {card.humour_line}
            </p>
          </CardRegion>
        )}

        {card.diagram && <Diagram spec={card.diagram} />}

        <Notice tone="warning">
          <span className="font-medium">Common beginner mistake. </span>
          {card.common_beginner_mistake}
        </Notice>

        {!canAfford && (
          <Notice tone="warning">
            You need more question credits to generate the questions. This concept card stays
            saved.
          </Notice>
        )}

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button onClick={onStart} disabled={busy || !canAfford}>
            <AppIcon icon={PlayIcon} size={16} />
            {t.startMicroQuestions}
          </Button>
          <Button
            variant="secondary"
            onClick={onSimplify}
            disabled={busy || atMax}
            loading={busy}
            loadingLabel={t.conceptStillDontGet}
          >
            <AppIcon icon={LightbulbIcon} size={16} />
            {atMax ? "That's as simple as it gets" : t.conceptStillDontGet}
          </Button>
          {simplifiedLevel > 0 && !atMax && (
            <Badge variant="outline">level {simplifiedLevel}</Badge>
          )}
        </div>
      </CardContent>
    </Card>
  );
}