import { z } from "zod";
import { approachIdSchema, isoDate, mistakeTypeSchema } from "./common";

export const usageSchema = z.object({
  question_credits_used: z.number().int().min(0),
  question_credits_limit: z.number().int().min(0),
  window_start: isoDate,
  window_end: isoDate,
  active_sessions: z.number().int().min(0),
  max_active_sessions: z.number().int().min(1),
  /** Minimum credits needed to generate a plan (3 per §16.5). */
  min_plan_credits: z.number().int().min(1),
});
export type Usage = z.infer<typeof usageSchema>;

export const conceptProgressSchema = z.object({
  concept: approachIdSchema,
  practice_count: z.number().int().min(0),
  mastery: z.number().min(0).max(1),
  last_practiced_at: isoDate.nullable().default(null),
});
export type ConceptProgress = z.infer<typeof conceptProgressSchema>;

export const weaknessSchema = z.object({
  concept: approachIdSchema,
  mistake_type: mistakeTypeSchema,
  weighted_count: z.number().min(0),
  distinct_problems: z.number().int().min(1),
  last_seen_at: isoDate,
});
export type Weakness = z.infer<typeof weaknessSchema>;

export const mistakeEntrySchema = z.object({
  id: z.string(),
  concept: approachIdSchema,
  mistake_type: mistakeTypeSchema,
  short_explanation: z.string(),
  problem_url: z.string(),
  source: z.enum(["judge", "revealed", "analysis"]),
  created_at: isoDate,
});
export type MistakeEntry = z.infer<typeof mistakeEntrySchema>;

export const reviewItemSchema = z.object({
  id: z.string(),
  concept: approachIdSchema,
  review_due_at: isoDate,
  priority: z.enum(["low", "normal", "high"]),
  box: z.number().int().min(1),
});
export type ReviewItem = z.infer<typeof reviewItemSchema>;

export const savedCardSchema = z.object({
  id: z.string(),
  slug: z.string(),
  title: z.string(),
  approach_id: approachIdSchema,
  kind: z.enum(["concept", "checklist"]),
  created_at: isoDate,
});
export type SavedCard = z.infer<typeof savedCardSchema>;

export const dailyActivitySchema = z.object({
  date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/),
  passed_questions: z.number().int().min(0),
});

export const progressSchema = z.object({
  xp: z.number().int().min(0),
  level: z.number().int().min(1),
  current_streak: z.number().int().min(0),
  longest_streak: z.number().int().min(0),
  mastery: z.array(conceptProgressSchema).default([]),
  weaknesses: z.array(weaknessSchema).default([]),
  mistake_type_counts: z
    .record(z.string(), z.number().int().min(0))
    .default({}),
  activity: z.array(dailyActivitySchema).max(120).default([]),
  due_reviews: z.number().int().min(0),
});
export type Progress = z.infer<typeof progressSchema>;