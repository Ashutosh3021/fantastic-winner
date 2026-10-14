import { z } from "zod";

/** ISO-8601 UTC timestamp. */
export const isoDate = z.string().min(1);

/** Languages the backend has a passing leak corpus for (§9.4). */
export const languageSchema = z.enum(["en", "hi", "or"]);
export type Language = z.infer<typeof languageSchema>;

export const difficultyModeSchema = z.enum(["beginner", "intermediate"]);
export type DifficultyMode = z.infer<typeof difficultyModeSchema>;

export const themeSchema = z.enum(["light", "dark", "system"]);
export type Theme = z.infer<typeof themeSchema>;

export const approachIdSchema = z.enum([
  "brute_force",
  "hash_map",
  "two_pointers",
  "sliding_window",
  "binary_search",
  "prefix_sum",
  "stack",
  "monotonic_stack",
  "heap",
  "dfs",
  "bfs",
  "backtracking",
  "dynamic_programming",
  "greedy",
  "sorting",
  "union_find",
  "trie",
  "bit_manipulation",
  "math",
]);
export type ApproachId = z.infer<typeof approachIdSchema>;

export const sessionStatusSchema = z.enum([
  "in_progress",
  "paused",
  "completed",
  "abandoned",
]);
export type SessionStatus = z.infer<typeof sessionStatusSchema>;

export const answerTypeSchema = z.enum([
  "single_choice",
  "multi_choice",
  "order_steps",
  "fill_blank",
  "predict_state",
  "short_text",
]);
export type AnswerType = z.infer<typeof answerTypeSchema>;

export const verdictSchema = z.enum(["correct", "partial", "incorrect"]);
export type Verdict = z.infer<typeof verdictSchema>;

export const mistakeTypeSchema = z.enum([
  "off_by_one",
  "wrong_data_structure",
  "missed_edge_case",
  "wrong_condition",
  "misunderstood_goal",
  "complexity_issue",
  "other",
]);
export type MistakeType = z.infer<typeof mistakeTypeSchema>;

export const complexityClassSchema = z.enum([
  "O(1)",
  "O(log n)",
  "O(n)",
  "O(n log n)",
  "O(n^2)",
  "O(n^3)",
  "O(2^n)",
  "O(n!)",
]);
export type ComplexityClass = z.infer<typeof complexityClassSchema>;

export const analysisConfidenceSchema = z.enum(["high", "medium", "low"]);

/** Field name on an extracted input variable, e.g. `n` or `s.length`. */
export const constraintBoundSchema = z.object({
  var: z.string().min(1),
  min: z.number().optional(),
  max: z.number().optional(),
});
export type ConstraintBound = z.infer<typeof constraintBoundSchema>;

/** Cached renderable content returned by a route. */
export const cacheMetaSchema = z.object({
  cached: z.boolean().default(false),
  cache_key: z.string().optional(),
  content_version: z.string().optional(),
});
export type CacheMeta = z.infer<typeof cacheMetaSchema>;

export const responseMetaSchema = z.object({
  cached: z.boolean().default(false),
  cache_key: z.string().optional(),
  content_version: z.string().optional(),
  credits_remaining: z.number().int().optional(),
  credits_reset_at: isoDate.optional(),
  credit_cost: z.number().int().optional(),
  prefs_version: z.number().int().optional(),
  request_id: z.string().optional(),
});
export type ResponseMeta = z.infer<typeof responseMetaSchema>;

export function envelope<T extends z.ZodTypeAny>(data: T) {
  return z.object({ data, meta: responseMetaSchema });
}