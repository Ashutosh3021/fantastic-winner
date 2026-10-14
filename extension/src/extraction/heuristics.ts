/**
 * Rung 3 of the extraction ladder: text heuristics (§5.3).
 *
 * When the statement has no usable structure we work off the description's
 * `innerText` and split on the markers LeetCode itself prints: `Example N:`,
 * `Constraints:`, `Follow up:`. This produces the same fields as rungs 1 and 2,
 * just with a lower `extraction_quality`.
 */

import { collapseWhitespace, elementText, stripInvisible } from "./html";
import { parseExamplesFromHtml } from "./embedded";

export type TextHeuristicExtraction = {
  title: string;
  statementText: string;
  examples: { input: string; output: string; explanation: string }[];
  constraintsText: string;
};

const DESCRIPTION_SELECTORS = [
  '[data-e2e-locator="question-detail-container"]',
  'div[id^="description"]',
  "main",
];

function descriptionText(): string {
  for (const selector of DESCRIPTION_SELECTORS) {
    const el = document.querySelector(selector);
    const text = elementText(el);
    if (text.length > 80) return text;
  }
  const main = document.querySelector("main");
  return collapseWhitespace(stripInvisible(main?.textContent ?? ""));
}

function firstHeading(): string {
  const h1 = document.querySelector("h1");
  const text = elementText(h1);
  if (text) return text;
  // Fall back to the slug, title-cased.
  const slug = window.location.pathname.split("/problems/")[1]?.split("/")[0] ?? "";
  return slug
    .split("-")
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function sectionAfter(text: string, marker: RegExp): string {
  const match = marker.exec(text);
  if (!match) return "";
  const start = match.index + match[0].length;
  const tail = text.slice(start);
  const stop = tail.search(/\n\s*(Example\s+\d+|Follow[- ]?up|Constraints)\b/i);
  return collapseWhitespace(stripInvisible(stop === -1 ? tail : tail.slice(0, stop)));
}

export function extractFromText(): TextHeuristicExtraction | null {
  const text = descriptionText();
  if (text.length < 80) return null;

  const title = firstHeading();
  if (!title) return null;

  const examples = parseExamplesFromHtml(text);
  const constraintsText = sectionAfter(text, /\bConstraints\s*:/i);
  const statementText = collapseWhitespace(
    stopBeforeExamples(text),
  );

  if (statementText.length < 40) return null;

  return { title, statementText, examples, constraintsText };
}

function stopBeforeExamples(text: string): string {
  const stop = text.search(/\bExample\s+\d+\s*:/i);
  const head = stop === -1 ? text : text.slice(0, stop);
  return collapseWhitespace(head);
}