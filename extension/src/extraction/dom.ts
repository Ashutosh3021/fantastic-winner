import { collapseWhitespace, elementText, htmlToPlainText, stripInvisible } from "./html";
import { parseExamplesFromHtml } from "./embedded";

/**
 * Rung 2 of the extraction ladder: semantic DOM selectors (§5.3).
 *
 * Everything here is anchored on hooks that mean something — headings, `aria-*`
 * roles, `data-*` attributes, `[id]` fragments — rather than hashed CSS class
 * names, which LeetCode rebuilds often. Every selector is a *candidate* list:
 * the first match wins, and rung 3 or 4 covers us when none match.
 */

export type DomExtraction = {
  title: string;
  statementText: string;
  examples: { input: string; output: string; explanation: string }[];
  constraintsText: string;
  tags: string[];
  difficulty: string;
  editorLanguage: string;
};

function firstText(selectors: string[], root: ParentNode = document): string {
  for (const selector of selectors) {
    let found: Element | null = null;
    try {
      found = root.querySelector(selector);
    } catch {
      continue; // Invalid selector for this document; try the next one.
    }
    const text = elementText(found);
    if (text) return text;
  }
  return "";
}

function firstElement(selectors: string[], root: ParentNode = document): HTMLElement | null {
  for (const selector of selectors) {
    try {
      const found = root.querySelector<HTMLElement>(selector);
      if (found) return found;
    } catch {
      continue;
    }
  }
  return null;
}

const TITLE_SELECTORS = [
  '[data-e2e-locator="question-title"]',
  'h1[id^="title"]',
  'div[id^="title"]',
  'h1[class*="css-"][class*="truncate"]',
  "main h1",
  "h1",
];

const DIFFICULTY_SELECTORS = [
  '[data-e2e-locator="difficulty"]',
  'span[id^=" difficulty-"]',
  'div[class*="text-difficulty"] span',
  '[class*="difficulty"]',
];

const STATEMENT_SELECTORS = [
  '[data-e2e-locator="question-detail-container"]',
  'div[class*="css-notranslate"][class*="markdown"]',
  'div[id^="description"]',
  'div[class*="_group_"][class*="space-y-"]',
  'section[role="region"]',
];

const CONSTRAINT_SELECTORS = [
  'div[id^="constraints"]',
  'div[class*="css-notranslate"][class*="markdown"]',
];

const TAG_SELECTORS = [
  'a[href*="/tag/"]',
  '[data-e2e-locator="topic-tag"]',
  'span[class*="rounded"][class*="bg-"][class*="text-"]',
];

const DESCRIPTION_CONTAINER_SELECTORS = [
  '[data-e2e-locator="question-detail-container"]',
  'div[id^="description"]',
  "main",
];

const EDITOR_LANGUAGE_SELECTORS = [
  'button[aria-label*="language" i]',
  '[data-e2e-locator="editor-language"]',
  'button[id^="headlessui-popover-button"]',
];

const DIFFICULTY_MAP: Record<string, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
};

function normalizeDifficulty(raw: string): string {
  const key = raw.trim().toLowerCase();
  return DIFFICULTY_MAP[key] ?? "Unknown";
}

function sectionFromText(statement: string, marker: string): string {
  const at = statement.search(new RegExp(`\\b${marker}\\b`, "i"));
  if (at === -1) return "";
  const tail = statement.slice(at);
  const stop = tail
    .slice(marker.length)
    .search(/\n\s*(Example\s+\d+|Follow[- ]?up)\b/i);
  return collapseWhitespace(stripInvisible(stop === -1 ? tail.slice(marker.length) : tail.slice(marker.length, marker.length + stop)));
}

export function extractFromDom(): DomExtraction | null {
  const container = firstElement(DESCRIPTION_CONTAINER_SELECTORS);
  if (!container) return null;

  const statementEl = firstElement(STATEMENT_SELECTORS, container) ?? container;
  const statementText = htmlToPlainText(statementEl.innerHTML);
  const title = firstText(TITLE_SELECTORS);

  if (!title || statementText.length < 40) return null;

  const constraintsEl = firstElement(CONSTRAINT_SELECTORS, container);
  const constraintsText = constraintsEl
    ? collapseWhitespace(elementText(constraintsEl))
    : sectionFromText(statementText, "Constraints:");

  const tagElements = TAG_SELECTORS.flatMap((selector) =>
    Array.from(document.querySelectorAll(selector)),
  );
  const tags = tagElements
    .map((el) => elementText(el))
    .filter((t): t is string => Boolean(t) && t.length <= 60)
    .filter((t, i, all) => all.indexOf(t) === i)
    .slice(0, 20);

  const editorLanguage = firstText(EDITOR_LANGUAGE_SELECTORS);

  return {
    title,
    statementText,
    examples: parseExamplesFromHtml(statementText),
    constraintsText,
    tags,
    difficulty: normalizeDifficulty(firstText(DIFFICULTY_SELECTORS)),
    editorLanguage: guessLanguage(editorLanguage),
  };
}

/** Map LeetCode's display names onto Monaco language ids. */
export function guessLanguage(label: string): string {
  const value = label.trim().toLowerCase();
  if (value.includes("python")) return "python3";
  if (value.includes("javascript")) return "javascript";
  if (value.includes("typescript")) return "typescript";
  if (value.includes("java")) return "java";
  if (value.includes("c++") || value.includes("cpp")) return "cpp";
  if (value.includes("c#") || value.includes("csharp")) return "csharp";
  if (value.includes("go")) return "go";
  if (value.includes("rust")) return "rust";
  if (value.includes("scala")) return "scala";
  if (value.includes("kotlin")) return "kotlin";
  if (value.includes("ruby")) return "ruby";
  if (value.includes("swift")) return "swift";
  return "";
}