import { z } from "zod";
import {
  approachIdSchema,
  difficultyModeSchema,
  isoDate,
  languageSchema,
  sessionStatusSchema,
  themeSchema,
} from "./common";
import { currentQuestionSchema, checklistResponseSchema } from "./microq";
import { conceptCardSchema, simplifiedConceptSchema } from "./diagram";
import { problemDataSchema } from "./problem";

export const sessionSummarySchema = z.object({
  id: z.string(),
  slug: z.string(),
  problem_url: z.string(),
  title: z.string(),
  selected_approach: approachIdSchema,
  status: sessionStatusSchema,
  unlocked_index: z.number().int().min(0),
  question_count: z.number().int().min(0).default(0),
  passed_count: z.number().int().min(0).default(0),
  content_version: z.number().int().min(1),
  mode: difficultyModeSchema,
  language: languageSchema,
  updated_at: isoDate,
});
export type SessionSummary = z.infer<typeof sessionSummarySchema>;

/** `GET /v1/sessions/{id}` — everything needed to render the current card. */
export const sessionStateSchema = z.object({
  session: sessionSummarySchema,
  question: currentQuestionSchema.nullable().default(null),
  checklist_unlocked: z.boolean(),
  analysis_unlocked: z.boolean(),
});
export type SessionState = z.infer<typeof sessionStateSchema>;

export const createSessionRequestSchema = z.object({
  slug: z.string().min(1),
  approach_id: approachIdSchema,
  problem: problemDataSchema,
});
export type CreateSessionRequest = z.infer<typeof createSessionRequestSchema>;

export const patchSessionRequestSchema = z.object({
  status: z.enum(["paused", "completed", "abandoned", "in_progress"]).optional(),
  approach_id: approachIdSchema.optional(),
});
export type PatchSessionRequest = z.infer<typeof patchSessionRequestSchema>;

/** Response to an approach switch: the cost is returned before anything commits. */
export const approachSwitchQuoteSchema = z.object({
  session_id: z.string(),
  credit_cost: z.number().int().min(0),
  credits_remaining: z.number().int().min(0),
  approach_id: approachIdSchema,
  /** True when the client must re-confirm; the switch has not been applied. */
  requires_confirmation: z.boolean().default(false),
});
export type ApproachSwitchQuote = z.infer<typeof approachSwitchQuoteSchema>;

export const conceptResponseSchema = z.object({
  card: conceptCardSchema,
  session_id: z.string(),
});
export type ConceptResponse = z.infer<typeof conceptResponseSchema>;

export const simplifyResponseSchema = z.object({
  simplified: simplifiedConceptSchema,
  session_id: z.string(),
});
export type SimplifyResponse = z.infer<typeof simplifyResponseSchema>;

export const generateQuestionsResponseSchema = z.object({
  session_id: z.string(),
  question: currentQuestionSchema,
  credits_charged: z.number().int().min(0),
});
export type GenerateQuestionsResponse = z.infer<typeof generateQuestionsResponseSchema>;

export const checklistApiSchema = z.object({
  session_id: z.string(),
  checklist: checklistResponseSchema,
});
export type ChecklistApi = z.infer<typeof checklistApiSchema>;

export const preferencesSchema = z.object({
  language: languageSchema,
  difficulty_mode: difficultyModeSchema,
  theme: themeSchema,
  timezone: z.string().min(1).max(64),
  prefs_version: z.number().int().min(1),
});
export type Preferences = z.infer<typeof preferencesSchema>;

export const preferencesPatchSchema = preferencesSchema.partial().omit({ prefs_version: true });
export type PreferencesPatch = z.infer<typeof preferencesPatchSchema>;

export const meSchema = z.object({
  id: z.string(),
  email: z.string(),
  email_verified: z.boolean(),
  created_at: isoDate,
  preferences: preferencesSchema,
  usage: z.object({
    question_credits_used: z.number().int().min(0),
    question_credits_limit: z.number().int().min(0),
    window_start: isoDate,
    window_end: isoDate,
    active_sessions: z.number().int().min(0),
  }),
});
export type Me = z.infer<typeof meSchema>;