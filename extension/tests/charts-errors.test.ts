import { describe, expect, it } from "vitest";

import { curveFor, verdictFor } from "../src/charts/scale";
import { isFinal, isRetryable, parseErrorCode, statusToCode } from "../src/api/errors";

describe("verdictFor", () => {
  it("calls a linear solution comfortable at the max input", () => {
    expect(verdictFor("O(n)", 50_000, 1e8).tone).toBe("good");
  });

  it("warns when the solution only just fits", () => {
    // O(n^2) at 5,000 is 25,000,000 — inside the budget but not by a lot.
    expect(verdictFor("O(n^2)", 5_000, 1e8).tone).toBe("warn");
  });

  it("calls a quadratic solution at 50,000 too slow", () => {
    // O(n^2) at 50,000 is 2.5e9, well past the rule-of-thumb budget.
    expect(verdictFor("O(n^2)", 50_000, 1e8).tone).toBe("bad");
  });

  it("does not mistake an exponential for something cheap", () => {
    expect(verdictFor("O(2^n)", 40, 1e8).tone).toBe("bad");
  });
});

describe("curveFor", () => {
  it("maps every class to a monotone non-decreasing function", () => {
    for (const label of ["O(1)", "O(log n)", "O(n)", "O(n log n)", "O(n^2)", "O(n^3)"]) {
      const fn = curveFor(label);
      expect(fn(1000), label).toBeGreaterThanOrEqual(fn(500));
    }
  });

  it("treats a multi-variable form as the product of its parts", () => {
    expect(curveFor("O(m*n)")(100)).toBe(curveFor("O(n^2)")(100));
  });

  it("falls back to linear for a shape it does not recognise", () => {
    // Better to draw the wrong-but-simple curve than to crash a chart.
    expect(curveFor("O(min(n, k)")(10)).toBe(10);
  });

  it("stays finite for n! past the double range", () => {
    expect(Number.isFinite(curveFor("O(n!)")(500))).toBe(true);
  });
});

describe("error helpers", () => {
  it("maps statuses onto stable codes when the body carries none", () => {
    expect(statusToCode(401)).toBe("unauthorized");
    expect(statusToCode(403)).toBe("email_unverified");
    expect(statusToCode(426)).toBe("upgrade_required");
    expect(statusToCode(429)).toBe("rate_limited");
    expect(statusToCode(503)).toBe("ai_unavailable");
    expect(statusToCode(418)).toBe("unknown");
  });

  it("does not guess at ambiguous statuses", () => {
    // 409 and 422 mean different things depending on the body code, so the
    // status alone must not be turned into a specific promise.
    expect(statusToCode(409)).toBe("unknown");
    expect(statusToCode(422)).toBe("unknown");
  });

  it("trusts a known code from the body over the status", () => {
    expect(parseErrorCode("ip_budget")).toBe("ip_budget");
    expect(parseErrorCode("something_new")).toBe("unknown");
  });

  it("retries transient failures and final failures exactly once, then stops", () => {
    expect(isRetryable("ai_busy")).toBe(true);
    expect(isRetryable("network_error")).toBe(true);
    expect(isRetryable("timeout")).toBe(true);
    expect(isRetryable("invalid_response")).toBe(false);

    // Retrying these cannot change the outcome (§16.2).
    expect(isFinal("credits_exhausted")).toBe(true);
    expect(isFinal("checklist_locked")).toBe(true);
    expect(isFinal("ai_output_truncated")).toBe(true);
    expect(isFinal("ip_budget")).toBe(false);
  });
});