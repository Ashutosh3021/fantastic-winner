import { describe, expect, it } from "vitest";

import { parseConstraintBounds, dominantMax } from "../src/extraction/constraints";

/**
 * The constraint parser decides `N_max` on the complexity chart and the size
 * band on the approach list. Getting `10^5` wrong by a factor of ten would put
 * the budget line in the wrong place on every chart, so the notation LeetCode
 * actually writes gets a table test.
 */
describe("parseConstraintBounds", () => {
  const cases: [string, string, { min?: number; max?: number }][] = [
    ["1 <= n <= 10^5", "n", { min: 1, max: 100_000 }],
    ["0 <= s.length <= 5 * 10^4", "s.length", { min: 0, max: 50_000 }],
    ["n <= 20", "n", { max: 20 }],
    ["-10^9 <= nums[i] <= 10^9", "nums[i]", { min: -1e9, max: 1e9 }],
    ["1 <= n < 1000", "n", { min: 1, max: 1000 }],
    ["0 <= k <= 2^31 - 1", "k", { min: 0, max: 2_147_483_647 }],
    ["2 <= numRows <= 200", "numRows", { min: 2, max: 200 }],
    ["1 <= n, m <= 100", "n", { min: 1, max: 100 }],
    ["3 <= target.length <= 1000", "target.length", { min: 3, max: 1000 }],
    ["n is at most 10^5", "n", { max: 100_000 }],
    ["1 <= s.length <= 10**5", "s.length", { min: 1, max: 100_000 }],
  ];

  for (const [input, variable, expected] of cases) {
    it(`parses "${input}"`, () => {
      const bounds = parseConstraintBounds(input);
      expect(bounds).toContainEqual({ var: variable, ...expected });
    });
  }

  it("does not invent bounds from prose without a comparison", () => {
    expect(parseConstraintBounds("The array contains positive integers.")).toEqual([]);
  });

  it("is stable regardless of whitespace and unicode operators", () => {
    expect(parseConstraintBounds("1<=n<=10^5")).toEqual(parseConstraintBounds("1  ≤  n  ≤  10^5"));
  });

  it("keeps the most permissive bound when a variable is constrained twice", () => {
    const bounds = parseConstraintBounds("n <= 20\nn <= 500");
    expect(bounds).toContainEqual({ var: "n", max: 500 });
  });

  it("caps the number of reported bounds", () => {
    const many = Array.from({ length: 40 }, (_, i) => `v${i} <= ${i + 1}`).join("\n");
    expect(parseConstraintBounds(many).length).toBeLessThanOrEqual(20);
  });
});

describe("dominantMax", () => {
  it("picks the largest upper bound", () => {
    expect(dominantMax(parseConstraintBounds("1 <= n <= 10^3\n1 <= m <= 5 * 10^4"))).toBe(50_000);
  });

  it("falls back when nothing parses", () => {
    expect(dominantMax([], 100_000)).toBe(100_000);
  });
});