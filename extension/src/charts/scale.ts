import type { ComplexityClass } from "../schemas";

/** Minimal log/power scale helpers. No chart library: plain SVG only (§13). */

export const CURVE_ORDER: ComplexityClass[] = [
  "O(1)",
  "O(log n)",
  "O(n)",
  "O(n log n)",
  "O(n^2)",
  "O(n^3)",
  "O(2^n)",
  "O(n!)",
];

type Fn = (n: number) => number;

const FACTORIAL_LIMIT = 170; // above this, n! overflows a double

export function curveFor(label: string): Fn {
  const value = label.trim();
  switch (value) {
    case "O(1)":
      return () => 1;
    case "O(log n)":
      return (n) => Math.log2(Math.max(2, n));
    case "O(n)":
      return (n) => n;
    case "O(n log n)":
      return (n) => n * Math.log2(Math.max(2, n));
    case "O(n^2)":
      return (n) => n * n;
    case "O(n^3)":
      return (n) => n ** 3;
    case "O(m*n)":
    case "O(nm)":
    case "O(n^2) 2 vars":
      return (n) => n * n;
    case "O(2^n)":
      return (n) => 2 ** Math.min(n, 1024);
    case "O(n!)":
      return (n) => (n <= 1 ? 1 : n <= FACTORIAL_LIMIT ? factorial(n) : Number.MAX_VALUE);
    default:
      // Unknown shapes (e.g. "O(min(n, k))") are drawn as O(n), never as a guess
      // the chart would present as fact.
      return (n) => n;
  }
}

function factorial(n: number): number {
  let out = 1;
  for (let i = 2; i <= n; i += 1) out *= i;
  return out;
}

export type Verdict = {
  tone: "good" | "warn" | "bad";
  label: string;
};

/** §13.1.3 verdict chip, driven by `f(N_max)` against the budget. */
export function verdictFor(label: string, nMax: number, budgetOps: number): Verdict {
  const operations = curveFor(label)(Math.max(2, nMax));
  if (operations <= 1e7) return { tone: "good", label: "Comfortable for the max input" };
  if (operations <= budgetOps) return { tone: "warn", label: "Fits, but not by a lot" };
  return { tone: "bad", label: "Likely too slow for the max input (TLE risk)" };
}