import { z } from "zod";
import {
  answerTypeSchema,
  mistakeTypeSchema,
  verdictSchema,
} from "./common";
import { learningDiagramSpecSchema } from "./diagram";

/**
 * The question shape the client is allowed to see (§10.4).
 *
 * The server never sends `rubric`, `common_wrong`, `step_explanation`, later
 * questions, or the checklist before the conditions in §11 are met. Anything
 * not in this schema is not a field we render.
 */
export const currentQuestionSchema = z.object({
  index: z.number().int().min(1),
  total: z.number().int().min(1),
  prompt: z.string(),
  learning_goal: z.string(),
  answer_type: answerTypeSchema,
  choices: z.array(z.string().max(200)).max(8).nullable().default(null),
  diagram: learningDiagramSpecSchema.nullable().default(null),
  hints_used: z.number().int().min(0).default(0),
  attempts: z.number().int().min(0).default(0),
  hints_available: z.boolean().default(false),
  step_explanation: z.string().nullable().default(null),
  revealed: z.boolean().default(false),
});
export type CurrentQuestion = z.infer<typeof currentQuestionSchema>;

export const hintResponseSchema = z.object({
  index: z.number().int().min(1),
  level: z.number().int().min(1).max(3),
  text: z.string(),
  is_last: z.boolean(),
});
export type HintResponse = z.infer<typeof hintResponseSchema>;

export const revealResponseSchema = z.object({
  session_id: z.string(),
  index: z.number().int().min(1),
  step_explanation: z.string(),
  revealed: z.boolean().default(true),
});
export type RevealResponse = z.infer<typeof revealResponseSchema>;

export const answerResponseSchema = z.object({
  verdict: verdictSchema,
  feedback: z.string(),
  matched_key_points: z.array(z.number().int()).default([]),
  mistake_type: mistakeTypeSchema.nullable().default(null),
  attempt_no: z.number().int().min(1),
  next_question: currentQuestionSchema.nullable().default(null),
  all_passed: z.boolean().default(false),
});
export type AnswerResponse = z.infer<typeof answerResponseSchema>;

export const checklistResponseSchema = z.object({
  items: z.array(z.string().min(1).max(240)).min(1).max(12),
  approach_id: z.string(),
});
export type ChecklistResponse = z.infer<typeof checklistResponseSchema>;

/** `predict_state` and `order_steps` payloads the client submits. */
export const answerSubmissionSchema = z.object({
  answer: z.string().max(4_000),
  choice_indexes: z.array(z.number().int().min(0)).max(12).optional(),
  order: z.array(z.number().int().min(0)).max(12).optional(),
  hints_used: z.number().int().min(0).max(3).default(0),
  time_taken_seconds: z.number().int().min(0).max(86_400).default(0),
});
export type AnswerSubmission = z.infer<typeof answerSubmissionSchema>;