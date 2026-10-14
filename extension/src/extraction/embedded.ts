import { collapseWhitespace, htmlToPlainText, stripInvisible } from "./html";

/**
 * Rung 1 of the extraction ladder: embedded page data (§5.3).
 *
 * LeetCode ships the problem as JSON in the document rather than as markup we
 * have to guess at. The exact wrapper key moves between deploys, so instead of
 * hard-coding a path we walk the parsed payload and look for an object that
 * *looks like* a question. If tomorrow's markup nests it somewhere else, this
 * still works; if the shape itself changes, rung 2 takes over.
 */

const MAX_DEPTH = 12;
const MAX_NODES = 20_000;

export type EmbeddedQuestion = {
  slug: string;
  title: string;
  contentHtml: string;
  difficulty: string;
  tags: string[];
  examples: { input: string; output: string; explanation: string }[];
  constraintsText: string;
  frontendQuestionId: string;
};

function looksLikeQuestion(value: Record<string, unknown>): boolean {
  const hasContent = typeof value.content === "string" && value.content.length > 0;
  const hasTitle =
    (typeof value.title === "string" && value.title.length > 0) ||
    (typeof value.titleSlug === "string" && value.titleSlug.length > 0);
  const hasId =
    typeof value.questionId === "string" ||
    typeof value.questionFrontendId === "string" ||
    typeof value.frontendQuestionId === "string";
  return hasContent && hasTitle && hasId;
}

function readString(source: Record<string, unknown>, keys: string[]): string | null {
  for (const key of keys) {
    const value = source[key];
    if (typeof value === "string" && value.trim()) return value;
  }
  return null;
}

function readTags(source: Record<string, unknown>): string[] {
  const raw = source.topicTags ?? source.tags;
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const entry of raw) {
    if (typeof entry === "string") {
      out.push(entry);
    } else if (entry && typeof entry === "object") {
      const name = (entry as Record<string, unknown>).name;
      if (typeof name === "string") out.push(name);
    }
  }
  return out.filter(Boolean).slice(0, 20);
}

function normalizeDifficulty(value: unknown): string {
  if (typeof value !== "string") return "Unknown";
  const lower = value.toLowerCase();
  if (lower.includes("easy")) return "Easy";
  if (lower.includes("medium")) return "Medium";
  if (lower.includes("hard")) return "Hard";
  return "Unknown";
}

function toQuestion(raw: Record<string, unknown>): EmbeddedQuestion {
  const contentHtml = typeof raw.content === "string" ? raw.content : "";
  const plain = htmlToPlainText(contentHtml);
  const slug =
    readString(raw, ["titleSlug", "slug", "questionSlug"]) ?? "";
  const frontendQuestionId =
    readString(raw, ["questionFrontendId", "frontendQuestionId", "questionId"]) ?? "";

  return {
    slug: slug.trim(),
    title: (readString(raw, ["title"]) ?? "Untitled problem").trim(),
    contentHtml,
    difficulty: normalizeDifficulty(raw.difficulty),
    tags: readTags(raw),
    examples: parseExamplesFromHtml(plain),
    constraintsText: sectionAfter(plain, ["Constraints:", "Constraints"]),
    frontendQuestionId,
  };
}

function sectionAfter(text: string, markers: string[]): string {
  const lower = text.toLowerCase();
  let best = -1;
  for (const marker of markers) {
    const at = lower.indexOf(marker.toLowerCase());
    if (at !== -1 && (best === -1 || at < best)) best = at;
  }
  if (best === -1) return "";
  const start = best + markers[0]!.length;
  const tail = text.slice(start);
  const stop = tail.search(/\n\s*(Example\s+\d+|Follow[- ]?up|Explanation)\b/i);
  return collapseWhitespace(stripInvisible(stop === -1 ? tail : tail.slice(0, stop)));
}

export function parseExamplesFromHtml(plainText: string): EmbeddedQuestion["examples"] {
  const examples: EmbeddedQuestion["examples"] = [];
  const re = /Example\s+(\d+)\s*:?/gi;
  const marks: { index: number; label: string }[] = [];
  for (const m of plainText.matchAll(re)) {
    if (m.index !== undefined && m[1]) marks.push({ index: m.index, label: m[1] });
  }

  for (let i = 0; i < marks.length && examples.length < 10; i += 1) {
    const start = marks[i]!.index;
    const end = i + 1 < marks.length ? marks[i + 1]!.index : plainText.length;
    const block = plainText.slice(start + `Example ${marks[i]!.label}:`.length, end).trim();

    const input = takeUntil(block, ["Input:", "Output:"]);
    const afterInput = block.slice(input.length);
    const output = takeUntil(afterInput, ["Output:", "Explanation:"]);
    const afterOutput = afterInput.slice(output.length);
    const explanation =
      afterOutput.match(/Explanation:\s*([\s\S]*)/i)?.[1]?.trim() ?? "";

    if (input.text.trim() || output.text.trim()) {
      examples.push({
        input: input.text.trim(),
        output: output.text.trim(),
        explanation: collapseWhitespace(explanation),
      });
    }
  }
  return examples;
}

function takeUntil(text: string, markers: string[]): { length: number; text: string } {
  let best = -1;
  let markerLength = 0;
  for (const marker of markers) {
    const at = text.indexOf(marker);
    if (at !== -1 && (best === -1 || at < best)) {
      best = at;
      markerLength = marker.length;
    }
  }
  if (best === -1) return { length: text.length, text: text };
  return { length: best + markerLength, text: text.slice(0, best) };
}

function deepFind(root: unknown): Record<string, unknown> | null {
  const queue: { node: unknown; depth: number }[] = [{ node: root, depth: 0 }];
  let visited = 0;

  while (queue.length > 0 && visited < MAX_NODES) {
    const { node, depth } = queue.shift()!;
    visited += 1;
    if (!node || typeof node !== "object" || depth > MAX_DEPTH) continue;

    if (Array.isArray(node)) {
      for (const child of node) queue.push({ node: child, depth: depth + 1 });
      continue;
    }
    const record = node as Record<string, unknown>;
    if (looksLikeQuestion(record)) return record;
    for (const child of Object.values(record)) {
      if (child && typeof child === "object") queue.push({ node: child, depth: depth + 1 });
    }
  }
  return null;
}

function parseScripts(): unknown[] {
  const roots: unknown[] = [];
  const candidates = document.querySelectorAll<HTMLScriptElement>(
    'script#__NEXT_DATA__, script[type="application/json"], script#__NUXT_DATA__',
  );
  for (const script of Array.from(candidates)) {
    try {
      roots.push(JSON.parse(script.textContent ?? ""));
    } catch {
      // Not JSON; ignore.
    }
  }

  // Some builds inline the payload on a global instead of a JSON script tag.
  const globals = window as unknown as Record<string, unknown>;
  for (const key of ["__INITIAL_STATE__", "__PRELOADED_STATE__", "__NEXT_DATA__"]) {
    if (globals[key]) roots.push(globals[key]);
  }
  return roots;
}

export function extractEmbedded(): EmbeddedQuestion | null {
  for (const root of parseScripts()) {
    const found = deepFind(root);
    if (found) {
      const question = toQuestion(found);
      if (question.title && question.contentHtml) return question;
    }
  }
  return null;
}