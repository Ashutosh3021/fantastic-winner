import { useState } from "react";
import type { IconSvgElement } from "@hugeicons/react";

import { Badge } from "../components/badge";
import { Button } from "../components/button";
import { Card, CardContent, CardDescription, CardHeader, CardRegion, CardTitle } from "../components/card";
import { Diagram } from "../components/diagram";
import { Notice } from "../components/field";
import { Textarea } from "../components/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from "../components/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../components/tabs";
import {
  AppIcon,
  Bug01Icon,
  CodeIcon,
  LightbulbIcon,
  MagicWand01Icon,
  SparklesIcon,
} from "../icons";
import { ComplexityGraph } from "../../charts/complexity";
import type { AnalysisResponse } from "../../schemas";

type Props = {
  analysis: AnalysisResponse | null;
  pending: boolean;
  /** Set when the bridge could not prove which buffer is the learner's. */
  ambiguous: boolean;
  onAnalyze: () => void;
};

/**
 * Solution analysis window (PLAN §3 Step 6).
 *
 * Reached only after Solution Mode. `EARNED` leak policy: code fragments are
 * from the learner's *own* code, and CodeMentor never writes into the LeetCode
 * editor. If the bridge was ambiguous we ask before sending anything (§14.2).
 */
export function AnalysisWindow({ analysis, pending, ambiguous, onAnalyze }: Props) {
  if (!analysis) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Solution Analysis</CardTitle>
          <CardDescription>
            Reads the solution out of the LeetCode editor and sends it for analysis. It is never
            written back into the editor.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {ambiguous && (
            <Notice tone="warning">
              More than one editor was open, so CodeMentor is not sure which one to read. Check the
              LeetCode editor is on your solution, then try again.
            </Notice>
          )}
          <div className="pt-1">
            <Button onClick={onAnalyze} disabled={pending} loading={pending} loadingLabel="Reading your editor">
              <AppIcon icon={CodeIcon} size={16} />
              {pending ? "Reading your editor…" : "Analyse the code in the editor"}
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Solution Analysis</CardTitle>
          <div className="flex flex-wrap gap-1.5">
            <Badge variant="outline">{analysis.time_class}</Badge>
            <Badge variant="neutral">{analysis.space_class}</Badge>
            {analysis.language_mismatch && (
              <Badge variant="warning">language mismatch</Badge>
            )}
          </div>
        </div>
      </CardHeader>

      <CardContent>
        <Tabs defaultValue="complexity">
          <TabsList>
            <TabsTrigger value="complexity">Complexity</TabsTrigger>
            <TabsTrigger value="code">Your code</TabsTrigger>
            <TabsTrigger value="improve">Improve</TabsTrigger>
            <TabsTrigger value="tricks">Related</TabsTrigger>
          </TabsList>

          <TabsContent value="complexity" className="flex flex-col gap-3">
            <ComplexityGraph chart={analysis.chart} timeClass={analysis.time_class} />
            <p className="text-sm leading-relaxed text-muted-foreground">
              {analysis.complexity_explanation}
            </p>
            {analysis.trace && <Diagram spec={analysis.trace} />}
          </TabsContent>

          <TabsContent value="code" className="flex flex-col gap-2.5">
            {analysis.line_explanations.length === 0 ? (
              <p className="text-sm leading-relaxed text-muted-foreground">
                Nothing worth singling out — the code is already short.
              </p>
            ) : (
              analysis.line_explanations.map((item, index) => (
                <CardRegion key={index}>
                  <p className="text-xs font-medium">{item.label}</p>
                  {item.quote && <pre className="cm-ascii">{item.quote}</pre>}
                  <p className="text-sm leading-relaxed text-muted-foreground">{item.why}</p>
                </CardRegion>
              ))
            )}
          </TabsContent>

          <TabsContent value="improve" className="flex flex-col gap-4">
            <Section
              icon={Bug01Icon}
              title="Edge cases your code might miss"
              items={analysis.edge_cases}
            />
            <Section
              icon={LightbulbIcon}
              title="Concrete improvements"
              items={analysis.improvement_suggestions}
            />
            {analysis.better_approach && (
              <CardRegion>
                <p className="flex flex-wrap items-center gap-1.5 text-xs font-medium">
                  <AppIcon icon={MagicWand01Icon} size={14} />
                  Another way to think about this
                  {analysis.better_approach.complexity && (
                    <Badge variant="outline">{analysis.better_approach.complexity}</Badge>
                  )}
                </p>
                <p className="text-sm leading-relaxed text-muted-foreground">
                  {analysis.better_approach.summary}
                </p>
              </CardRegion>
            )}
          </TabsContent>

          <TabsContent value="tricks">
            <Section icon={SparklesIcon} title="Tricks that transfer" items={analysis.related_tricks} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

function Section({
  icon,
  title,
  items,
}: {
  icon: IconSvgElement;
  title: string;
  items: string[];
}) {
  if (items.length === 0) {
    return <p className="text-sm leading-relaxed text-muted-foreground">Nothing flagged here.</p>;
  }
  return (
    <section className="flex flex-col gap-1.5">
      <p className="flex items-center gap-1.5 text-xs font-medium">
        <AppIcon icon={icon} size={14} className="text-muted-foreground" />
        {title}
      </p>
      <ul className="flex list-disc flex-col gap-1 pl-4 text-sm leading-relaxed text-muted-foreground marker:text-muted-foreground/50">
        {items.map((item, index) => (
          <li key={index}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

const EDITOR_LANGUAGES = [
  "python3",
  "javascript",
  "typescript",
  "java",
  "cpp",
  "csharp",
  "go",
  "rust",
  "scala",
  "kotlin",
  "ruby",
  "swift",
];

/** Rung-4 fallback: the bridge could not read the editor, so ask for a paste. */
export function PasteCodePanel({
  onAnalyze,
  busy,
}: {
  onAnalyze: (code: string, editorLanguage: string) => void;
  busy: boolean;
}) {
  const [code, setCode] = useState("");
  const [language, setLanguage] = useState("python3");

  return (
    <Card>
      <CardHeader>
        <CardTitle>Paste your code</CardTitle>
        <CardDescription>
          CodeMentor could not read the editor, so paste your solution here instead. It is sent for
          analysis and never written back into the editor.
        </CardDescription>
      </CardHeader>

      <CardContent>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="paste-language"
              className="text-xs leading-4 font-medium text-foreground"
            >
              Language
            </label>
            <Select value={language} onValueChange={setLanguage}>
              <SelectTrigger id="paste-language">{language}</SelectTrigger>
              <SelectContent>
                {EDITOR_LANGUAGES.map((id) => (
                  <SelectItem key={id} value={id}>
                    {id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="flex flex-col gap-1.5">
            <label htmlFor="paste-code" className="text-xs leading-4 font-medium text-foreground">
              Your solution
            </label>
            <Textarea
              id="paste-code"
              rows={10}
              className="font-mono text-xs"
              placeholder="class Solution: …"
              value={code}
              onChange={(event) => setCode(event.target.value)}
            />
          </div>

          <div className="pt-1">
            <Button
              onClick={() => onAnalyze(code, language)}
              disabled={busy || code.trim().length === 0}
              loading={busy}
              loadingLabel="Analysing your code"
            >
              Analyse
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}