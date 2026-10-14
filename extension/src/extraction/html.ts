/**
 * HTML → plain text.
 *
 * `statement_text` must survive `10^5` (LeetCode renders superscripts as
 * `<sup>`), keep paragraph boundaries for the text heuristics in rung 3, and
 * contain no markup — the prompt wraps it as data and the leak detector scans
 * it as text (§5.3, §15.5).
 */

const BLOCK_TAGS = new Set([
  "P", "DIV", "SECTION", "ARTICLE", "UL", "OL", "LI", "TABLE", "TR",
  "H1", "H2", "H3", "H4", "H5", "H6", "PRE", "BLOCKQUOTE", "HR", "BR",
]);

const SKIP_TAGS = new Set(["SCRIPT", "STYLE", "NOSCRIPT", "TEMPLATE", "SVG", "IFRAME"]);

const NAMED_ENTITIES: Record<string, string> = {
  amp: "&", lt: "<", gt: ">", quot: '"', apos: "'", nbsp: " ",
  le: "≤", ge: "≥", times: "×", minus: "−", hellip: "…",
  mdash: "—", ndash: "–", rarr: "→", larr: "←", uarr: "↑",
  darr: "↓", ne: "≠", leq: "≤", geq: "≥",
};

export function decodeEntities(input: string): string {
  return input.replace(/&(#x?[0-9a-f]+|[a-z]+);/gi, (match, body: string) => {
    if (body.startsWith("#x") || body.startsWith("#X")) {
      const code = Number.parseInt(body.slice(2), 16);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    if (body.startsWith("#")) {
      const code = Number.parseInt(body.slice(1), 10);
      return Number.isFinite(code) ? String.fromCodePoint(code) : match;
    }
    const named = NAMED_ENTITIES[body.toLowerCase()];
    return named ?? match;
  });
}

/** Zero-width and control characters make cache keys unstable; drop them. */
export function stripInvisible(input: string): string {
  // eslint-disable-next-line no-control-regex
  return input.replace(/[\u0000-\u0008\u000B\u000C\u000E-\u001F\u007F\u200B-\u200D\u2060\uFEFF]/g, "");
}

export function collapseWhitespace(input: string): string {
  return input
    .replace(/\r\n?/g, "\n")
    .replace(/[ \t]+/g, " ")
    .replace(/ *\n */g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

export function htmlToPlainText(html: string): string {
  if (!html) return "";
  const doc = new DOMParser().parseFromString(`<body>${html}</body>`, "text/html");

  const walk = (node: Node, out: string[]): void => {
    if (node.nodeType === Node.TEXT_NODE) {
      out.push(node.textContent ?? "");
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;

    const el = node as HTMLElement;
    const tag = el.tagName.toUpperCase();
    if (SKIP_TAGS.has(tag)) return;

    if (tag === "BR") {
      out.push("\n");
      return;
    }
    if (tag === "SUP") {
      out.push("^");
      for (const child of Array.from(el.childNodes)) walk(child, out);
      return;
    }
    if (tag === "SUB") {
      out.push("_");
      for (const child of Array.from(el.childNodes)) walk(child, out);
      return;
    }
    if (tag === "CODE" || tag === "PRE") {
      // Inline code in a statement is part of the problem (variable names,
      // literal input formats). Keep the text; the leak detector works on the
      // rendered result, not on tags.
      for (const child of Array.from(el.childNodes)) walk(child, out);
      return;
    }

    const isBlock = BLOCK_TAGS.has(tag);
    if (isBlock) out.push("\n");
    for (const child of Array.from(el.childNodes)) walk(child, out);
    if (isBlock) out.push("\n");
  };

  const parts: string[] = [];
  for (const child of Array.from(doc.body.childNodes)) walk(child, parts);
  return collapseWhitespace(stripInvisible(decodeEntities(parts.join(""))));
}

/** Visible text of an element, normalized the same way as `htmlToPlainText`. */
export function elementText(el: Element | null | undefined): string {
  if (!el) return "";
  return collapseWhitespace(stripInvisible(decodeEntities(el.textContent ?? "")));
}

export function truncate(text: string, max: number): string {
  return text.length <= max ? text : `${text.slice(0, Math.max(0, max - 1))}…`;
}