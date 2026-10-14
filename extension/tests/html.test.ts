import { describe, expect, it } from "vitest";

import { collapseWhitespace, decodeEntities, htmlToPlainText, stripInvisible } from "../src/extraction/html";

describe("htmlToPlainText", () => {
  it("turns superscripts into exponent notation so 10^5 survives", () => {
    // LeetCode renders 10^5 as 10<sup>5</sup>; losing that turns a huge bound
    // into a tiny one on the complexity chart.
    expect(htmlToPlainText("<p>n is at most 10<sup>5</sup>.</p>")).toBe("n is at most 10^5.");
  });

  it("keeps paragraph boundaries for the text heuristics", () => {
    const text = htmlToPlainText("<p>First.</p><p>Second.</p>");
    expect(text.split("\n\n")).toHaveLength(2);
  });

  it("turns <br> into a line break", () => {
    expect(htmlToPlainText("a<br>b")).toBe("a\nb");
  });

  it("keeps inline code, which is part of the problem statement", () => {
    expect(htmlToPlainText("<code>s.length</code>")).toBe("s.length");
  });

  it("drops scripts and styles entirely", () => {
    const text = htmlToPlainText("<p>keep</p><script>drop()</script><style>.a{}</style>");
    expect(text).toBe("keep");
  });

  it("decodes the comparison operators LeetCode writes literally", () => {
    expect(htmlToPlainText("<p>1 &lt;= n &le; 10<sup>5</sup></p>")).toBe("1 <= n ≤ 10^5");
  });

  it("strips zero-width characters so cache keys stay stable", () => {
    expect(htmlToPlainText("<p>a\u200bb</p>")).toBe("ab");
  });

  it("returns an empty string for empty input", () => {
    expect(htmlToPlainText("")).toBe("");
  });
});

describe("decodeEntities", () => {
  it("decodes numeric and named entities", () => {
    expect(decodeEntities("&#8212; &mdash; &unknown;")).toBe("— — &unknown;");
  });
});

describe("collapseWhitespace", () => {
  it("collapses runs of spaces and blank lines", () => {
    expect(collapseWhitespace("a   b\n\n\n\nc")).toBe("a b\n\nc");
  });
});

describe("stripInvisible", () => {
  it("removes zero-width and control characters", () => {
    expect(stripInvisible("a\u200bc\u0007d")).toBe("acd");
  });

  it("keeps tab and newline, which carry structure", () => {
    expect(stripInvisible("a\tb\nc")).toBe("a\tb\nc");
  });
});