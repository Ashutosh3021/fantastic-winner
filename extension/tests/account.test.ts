import { describe, expect, it } from "vitest";

import { ROUTES } from "../src/api/routes";
import { aiKeyInputSchema, aiKeySchema, meSchema } from "../src/schemas";

const BASE_ME = {
  id: "user-1",
  email: "learner@example.com",
  email_verified: true,
  created_at: "2026-01-01T00:00:00Z",
  preferences: {
    language: "en",
    difficulty_mode: "beginner",
    theme: "system",
    timezone: "UTC",
    prefs_version: 1,
  },
  usage: {
    question_credits_used: 0,
    question_credits_limit: 12,
    window_start: "2026-01-01T00:00:00Z",
    window_end: "2026-01-01T05:00:00Z",
    active_sessions: 0,
    max_active_sessions: 3,
    min_plan_credits: 3,
  },
};

describe("account AI key routes", () => {
  it("uses the documented methods and path", () => {
    expect(ROUTES.aiKeyGet).toMatchObject({ method: "GET", path: "/account/ai-key" });
    expect(ROUTES.aiKeyPut).toMatchObject({ method: "PUT", path: "/account/ai-key" });
    expect(ROUTES.aiKeyDelete).toMatchObject({ method: "DELETE", path: "/account/ai-key" });
  });

  it("accepts a metadata-only GET response and rejects a raw key field", () => {
    expect(ROUTES.aiKeyGet.response.safeParse(null).success).toBe(true);
    expect(
      ROUTES.aiKeyGet.response.safeParse({
        provider: "openai",
        hint: "1234",
        updatedAt: "2026-01-01T00:00:00Z",
        api_key: "sk-should-never-arrive",
      }).success,
    ).toBe(false);
  });
});

describe("AI key schemas", () => {
  it("requires a provider and a plausible key length", () => {
    expect(
      aiKeyInputSchema.safeParse({ provider: "openai", api_key: "short" }).success,
    ).toBe(false);
    expect(
      aiKeyInputSchema.safeParse({ provider: "openai", api_key: "sk-live-12345678" })
        .success,
    ).toBe(true);
  });

  it("only knows the three supported providers", () => {
    expect(
      aiKeySchema.safeParse({
        provider: "cohere",
        hint: "1234",
        updatedAt: "2026-01-01T00:00:00Z",
      }).success,
    ).toBe(false);
  });
});

describe("me schema", () => {
  it("defaults older responses to tier 0 with no key", () => {
    const parsed = meSchema.parse(BASE_ME);
    expect(parsed.planTier).toBe(0);
    expect(parsed.aiKey).toBeNull();
  });

  it("carries the tier and masked key metadata", () => {
    const parsed = meSchema.parse({
      ...BASE_ME,
      planTier: 1,
      aiKey: { provider: "anthropic", hint: "9f2a", updatedAt: "2026-01-02T00:00:00Z" },
    });
    expect(parsed.planTier).toBe(1);
    expect(parsed.aiKey).toEqual({
      provider: "anthropic",
      hint: "9f2a",
      updatedAt: "2026-01-02T00:00:00Z",
    });
  });
});
