import type { ConstraintBound } from "../schemas";

/**
 * Constraint-bound parser (§5.3).
 *
 * `constraint_bounds` feeds two things: the target-complexity band used when
 * choosing approaches (§8), and `n_max` on the complexity chart (§13.1.3). Both
 * are wrong by orders of magnitude if `10^5` parses as `10`, so this module
 * understands the notation LeetCode actually writes.
 *
 * Supported shapes:
 *   `1 <= n <= 10^5`            → { var: "n", min: 1, max: 100000 }
 *   `0 <= s.length <= 5 * 10^4` → { var: "s.length", min: 0, max: 50000 }
 *   `n <= 20`                   → { var: "n", max: 20 }
 *   `-10^9 <= nums[i] <= 10^9`  → { var: "nums[i]", min: -1e9, max: 1e9 }
 *   `1 <= n, m <= 100`          → two bounds
 *   `10**5`, `2^31 - 1`, `1e5`  → numeric literals
 */

const SIGN = String.raw`[-+]?`;
/**
 * A constraint literal: a base number, optional `* 10^k` / `^k` terms, and an
 * optional trailing arithmetic term so `2^31 - 1` parses the way it reads.
 */
const NUMBER = String.raw`\d[\d_]*(?:\s*(?:\*\*|\^|\*)\s*\d[\d_]*)*(?:\s*[-+]\s*\d[\d_]*)?|\d+(?:\.\d+)?[eE][+-]?\d+`;

/** A numeric literal with an optional sign, e.g. `-10^9` or `+ 5`. */
const NUMBER_WITH_SIGN = `${SIGN}\\s*${NUMBER}`;

/**
 * Evaluate a single numeric term: `42`, `10^5`, `5 * 10^4`, `-2^31`, `2^31 - 1`
 * (as an additive tail).
 *
 * Returns `null` rather than guessing when the notation is not recognised, so
 * an unparsed bound falls back to the documented default instead of putting a
 * wrong number on a chart.
 */
function evaluateNumeric(expression: string): number | null {
  const compact = expression.replace(/[_\s]/g, "");
  if (!compact) return null;

  // Additive tail: `2^31 - 1`, `1e9 + 7`. Split it off and recurse on the head.
  const additive = compact.match(/^([+-]?[^-+]+)((?:[-+]\d+)+)$/);
  if (additive) {
    let acc = evaluateTerm(additive[1]!);
    if (acc === null) return null;
    for (const part of (additive[2]!).matchAll(/([-+])(\d+)/g)) {
      const value = Number(part[2]);
      acc += part[1] === "-" ? -value : value;
    }
    return Number.isFinite(acc) ? acc : null;
  }

  return evaluateTerm(compact);
}

/** A term with no top-level `+` or `-`. */
function evaluateTerm(term: string): number | null {
  const direct = Number(term);
  if (Number.isFinite(direct)) return direct;

  // `NUM * 10^k` — the shape LeetCode uses for round limits.
  const times = term.match(new RegExp(`^([-+]?\\d+)\\*10\\^?\\*?\\*?(\\d+)$`));
  if (times) return Number(times[1]) * 10 ** Number(times[2]);

  // `10^k`, `2^31`, and left-associative `a^b^c`.
  const pow = term.match(new RegExp(`^([-+]?\\d+)(?:\\^|\\*\\*)(\\d+)$`));
  if (pow) return Number(pow[1]) ** Number(pow[2]);

  const chainedPow = term.match(new RegExp(`^([-+]?\\d+)(?:\\^|\\*\\*)(\\d+)(?:\\^|\\*\\*)(\\d+)$`));
  if (chainedPow) return Number(chainedPow[1]) ** Number(chainedPow[2]) ** Number(chainedPow[3]);

  return null;
}

function isNumeric(text: string): boolean {
  return new RegExp(`^[-+]?\\s*${NUMBER}$`).test(text.trim());
}

const VAR = String.raw`[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+|\[[^\]]+\]|\[\d+\])*`;

function bound(text: string | undefined): number | null {
  if (text === undefined) return null;
  return isNumeric(text) ? evaluateNumeric(text) : null;
}

function push(map: Map<string, ConstraintBound>, name: string, field: "min" | "max", value: number) {
  if (!Number.isFinite(value)) return;
  const key = name.replace(/\s+/g, "");
  const existing = map.get(key);
  const next: ConstraintBound = existing ? { ...existing } : { var: key };
  // Keep the most permissive bound seen; constraints are sometimes repeated.
  if (field === "min") next.min = next.min === undefined ? value : Math.min(next.min, value);
  if (field === "max") next.max = next.max === undefined ? value : Math.max(next.max, value);
  map.set(key, next);
}

function scan(text: string, map: Map<string, ConstraintBound>): void {
  const source = text.replace(/≤/g, "<=").replace(/≥/g, ">=");

  /**
   * Chains: `NUM <= VAR <= VAR ... <= NUM`, covering both `1 <= n <= 10^5` and
   * the multi-variable forms `1 <= n <= m <= 100` and `1 <= n, m <= 100`.
   * Every variable in the chain shares both bounds, which is the reading
   * LeetCode intends in all three shapes.
   */
  const chained = new RegExp(
    `(${NUMBER_WITH_SIGN})\\s*(?:<=|<)\\s*(${VAR}(?:\\s*(?:<=|<|,)\\s*${VAR})*)` +
      `\\s*(?:<=|<)\\s*(${NUMBER_WITH_SIGN})`,
    "g",
  );
  for (const match of source.matchAll(chained)) {
    const [, lowText, varChain, highText] = match;
    if (!lowText || !varChain || !highText) continue;

    const names = varChain.split(/\s*(?:<=|<|,)\s*/).filter(Boolean);
    const low = bound(lowText);
    const high = bound(highText);
    if (low === null && high === null) continue;

    for (const name of names) {
      if (low !== null) push(map, name, "min", low);
      if (high !== null) push(map, name, "max", high);
    }
  }

  // Single: NUM <= VAR  or  VAR <= NUM
  const singleLow = new RegExp(`(${NUMBER_WITH_SIGN})\\s*(?:<=|<)\\s*(${VAR})`, "g");
  for (const match of source.matchAll(singleLow)) {
    const [, lowText, name] = match;
    if (!lowText || !name) continue;
    if (new RegExp(`^${VAR}$`).test(lowText.trim())) continue;
    const low = bound(lowText);
    if (low !== null) push(map, name, "min", low);
  }

  const singleHigh = new RegExp(`(${VAR})\\s*(?:<=|<)\\s*(${NUMBER_WITH_SIGN})`, "g");
  for (const match of source.matchAll(singleHigh)) {
    const [, name, highText] = match;
    if (!name || !highText) continue;
    if (new RegExp(`^${VAR}$`).test(highText.trim())) continue;
    const high = bound(highText);
    if (high !== null) push(map, name, "max", high);
  }

  // Bare upper bounds phrased as "n is at most 20" / "up to 10^5".
  const phrase = new RegExp(
    `(${VAR})\\s+(?:is\\s+)?(?:at\\s+most|no\\s+more\\s+than|up\\s+to)\\s+(${NUMBER_WITH_SIGN})`,
    "gi",
  );
  for (const match of source.matchAll(phrase)) {
    const [, name, highText] = match;
    if (!name || !highText) continue;
    const high = bound(highText);
    if (high !== null) push(map, name, "max", high);
  }
}

/** Parse every bound we can find. Returns at most 20 entries. */
export function parseConstraintBounds(text: string): ConstraintBound[] {
  const map = new Map<string, ConstraintBound>();
  if (!text) return [];
  scan(text, map);
  return Array.from(map.values())
    .filter((b) => b.min !== undefined || b.max !== undefined)
    .slice(0, 20);
}

/**
 * The dominant input size for the complexity chart (§13.1.3): the largest
 * upper bound. Falls back to `1e5` and is labelled "assumed" by the caller.
 */
export function dominantMax(bounds: ConstraintBound[], fallback = 100_000): number {
  let best = 0;
  for (const item of bounds) {
    const value = item.max ?? item.min ?? 0;
    if (value > best) best = value;
  }
  return best > 0 ? best : fallback;
}