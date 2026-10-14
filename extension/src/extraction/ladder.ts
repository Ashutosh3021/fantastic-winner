/**
 * The extraction ladder (§5.3) and the `ProblemData` it produces.
 *
 * Order: embedded JSON → semantic DOM → text heuristics → manual paste.
 * Each rung that succeeds records how much it trusted itself, so the backend
 * and the metrics can see extraction drift before the selectors rot (§22.2).
 */

import type { ProblemData } from "../schemas";
import { extractEmbedded } from "./embedded";
import { extractFromDom, guessLanguage } from "./dom";
import { extractFromText } from "./heuristics";
import { parseConstraintBounds } from "./constraints";
import { collapseWhitespace, stripInvisible } from "./html";

export type Rung = "embedded" | "dom" | "text" | "manual";

export type ExtractionResult = {
  problem: ProblemData | null;
  /** Highest rung that produced a usable result. */
  rung: Rung | null;
  /** Every rung attempted, for metrics. */
  attempted: Rung[];
};

const SLUG_RE = /^([a-z0-9-]+)\/?$/;

export function slugFromUrl(url: string = window.location.href): string | null {
  try {
    const parsed = new URL(url);
    const match = parsed.pathname.match(/\/problems\/([^/]+)/);
    const slug = match?.[1];
    if (!slug) return null;
    return SLUG_RE.test(slug) ? slug : slug.toLowerCase().replace(/[^a-z0-9-]+/g, "-");
  } catch {
    return null;
  }
}

function normalizeTitle(title: string, slug: string): string {
  const trimmed = collapseWhitespace(stripInvisible(title));
  if (trimmed && trimmed.toLowerCase() !== "problem") return trimmed;
  return slug
    .split("-")
    .filter(Boolean)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/**
 * `content_hash` is a *drift hint only* (§5.3, §15.8). The server recomputes
 * its own hash from normalised text and ignores a mismatch, so a cosmetic
 * difference here costs nothing.
 */
async function hashContent(statement: string, constraints: string): Promise<string | undefined> {
  try {
    const bytes = new TextEncoder().encode(`${statement}\n${constraints}`);
    const digest = await crypto.subtle.digest("SHA-256", bytes);
    const hex = Array.from(new Uint8Array(digest))
      .map((b) => b.toString(16).padStart(2, "0"))
      .join("");
    return `sha256:${hex}`;
  } catch {
    return undefined;
  }
}

function buildProblem(input: {
  slug: string;
  title: string;
  statementText: string;
  examples: ProblemData["examples"];
  constraintsText: string;
  tags: string[];
  difficulty: string;
  editorLanguage: string;
  quality: "full" | "partial" | "manual";
}): ProblemData {
  const statementText = collapseWhitespace(stripInvisible(input.statementText)).slice(0, 20_000);
  const constraintsText = collapseWhitespace(stripInvisible(input.constraintsText)).slice(0, 5_000);

  return {
    slug: input.slug,
    url: `https://leetcode.com/problems/${input.slug}/`,
    title: normalizeTitle(input.title, input.slug),
    difficulty:
      input.difficulty === "Easy" || input.difficulty === "Medium" || input.difficulty === "Hard"
        ? input.difficulty
        : "Unknown",
    statement_text: statementText,
    examples: input.examples.slice(0, 10),
    constraints_text: constraintsText,
    constraint_bounds: parseConstraintBounds(constraintsText || statementText),
    tags: input.tags.slice(0, 20),
    editor_language: input.editorLanguage || guessLanguage(""),
    extraction_quality: input.quality,
  };
}

function isUsable(problem: ProblemData | null): problem is ProblemData {
  return Boolean(problem && problem.statement_text.length >= 40);
}

/** One pass down the ladder. Never throws; the caller decides about retrying. */
export function extractOnce(slug: string): ExtractionResult {
  const attempted: Rung[] = [];
  let candidate: ProblemData | null = null;
  let rung: Rung | null = null;

  // Rung 1 — embedded JSON.
  attempted.push("embedded");
  const embedded = extractEmbedded();
  if (embedded && embedded.contentHtml) {
    const html = embedded.contentHtml;
    const statement = collapseWhitespace(
      stripInvisible(html.replace(/<[^>]*>/g, (m) => (/^<(sup)\b/i.test(m) ? "^" : /^<(br)\b/i.test(m) ? "\n" : " "))),
    );
    candidate = buildProblem({
      slug: embedded.slug || slug,
      title: embedded.title,
      statementText: statement,
      examples: embedded.examples,
      constraintsText: embedded.constraintsText,
      tags: embedded.tags,
      difficulty: embedded.difficulty,
      editorLanguage: guessLanguage(""),
      quality: "full",
    });
    if (isUsable(candidate)) rung = "embedded";
  }

  // Rung 2 — semantic DOM.
  if (!rung) {
    attempted.push("dom");
    const dom = extractFromDom();
    if (dom) {
      candidate = buildProblem({
        slug,
        title: dom.title,
        statementText: dom.statementText,
        examples: dom.examples,
        constraintsText: dom.constraintsText,
        tags: dom.tags,
        difficulty: dom.difficulty,
        editorLanguage: dom.editorLanguage,
        quality: "full",
      });
      if (isUsable(candidate)) rung = "dom";
    }
  }

  // Rung 3 — text heuristics.
  if (!rung) {
    attempted.push("text");
    const text = extractFromText();
    if (text) {
      candidate = buildProblem({
        slug,
        title: text.title,
        statementText: text.statementText,
        examples: text.examples,
        constraintsText: text.constraintsText,
        tags: [],
        difficulty: "Unknown",
        editorLanguage: "",
        quality: "partial",
      });
      if (isUsable(candidate)) rung = "text";
    }
  }

  return { problem: rung ? candidate : null, rung, attempted };
}

export type ExtractOptions = {
  attempts?: number;
  baseDelayMs?: number;
  slug?: string;
};

/**
 * Walk the ladder, retrying with backoff while the page is still rendering
 * (the description arrives a beat after the route does) before giving up and
 * letting the UI fall back to manual paste (§5.2).
 */
export async function extractProblem(options: ExtractOptions = {}): Promise<ExtractionResult> {
  const attempts = options.attempts ?? 5;
  const baseDelayMs = options.baseDelayMs ?? 300;
  const slug = options.slug ?? slugFromUrl();
  if (!slug) return { problem: null, rung: null, attempted: [] };

  let last: ExtractionResult = { problem: null, rung: null, attempted: [] };

  for (let i = 0; i < attempts; i += 1) {
    last = extractOnce(slug);
    if (last.problem) {
      last.problem.content_hash = await hashContent(
        last.problem.statement_text,
        last.problem.constraints_text,
      );
      return last;
    }
    await new Promise((r) => setTimeout(r, baseDelayMs * 2 ** i));
  }

  return last;
}

/** Rung 4 — the learner pastes the statement by hand. */
export async function manualProblem(slug: string, raw: string): Promise<ProblemData> {
  const constraintsText = extractSection(raw, /\bConstraints\s*:/i);
  const problem = buildProblem({
    slug,
    title: extractSection(raw, /^\s*(.+)$/m) ?? slug,
    statementText: raw,
    examples: [],
    constraintsText,
    tags: [],
    difficulty: "Unknown",
    editorLanguage: "",
    quality: "manual",
  });
  problem.content_hash = await hashContent(problem.statement_text, problem.constraints_text);
  return problem;
}

function extractSection(text: string, marker: RegExp): string {
  const match = marker.exec(text);
  if (!match) return "";
  const tail = text.slice(match.index + match[0].length);
  return collapseWhitespace(stripInvisible(tail));
}

export * from "./constraints";
export * from "./html";