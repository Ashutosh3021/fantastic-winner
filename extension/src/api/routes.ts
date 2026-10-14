import { z } from "zod";
import {
  analysisRequestSchema,
  analysisResponseSchema,
  answerResponseSchema,
  answerSubmissionSchema,
  approachesRequestSchema,
  approachesResponseSchema,
  checklistApiSchema,
  conceptCardSchema,
  createSessionRequestSchema,
  currentQuestionSchema,
  generateQuestionsResponseSchema,
  hintResponseSchema,
  meSchema,
  mistakeEntrySchema,
  patchSessionRequestSchema,
  preferencesPatchSchema,
  preferencesSchema,
  progressSchema,
  reviewItemSchema,
  savedCardSchema,
  sessionStateSchema,
  sessionSummarySchema,
  simplifiedConceptSchema,
  usageSchema,
} from "../schemas";

/**
 * Every backend route the extension uses (§20), with its request body schema
 * and response schema. Keeping them in one table makes the service worker a
 * thin dispatcher and stops the content script from assembling URLs.
 *
 * `idempotent: true` marks routes that require an `Idempotency-Key`; the
 * client mints one UUID per user action and reuses it across retries, which is
 * what makes a retry after a timeout safe (§5.7, §16.5).
 */
export const ROUTES = {
  me: { method: "GET", path: "/me", response: meSchema, class: "light" },
  meDelete: { method: "DELETE", path: "/me", response: z.null(), class: "auth" },

  preferences: {
    method: "PUT",
    path: "/preferences",
    body: preferencesPatchSchema,
    response: preferencesSchema,
    class: "light",
  },

  approaches: {
    method: "POST",
    path: "/problems/approaches",
    body: approachesRequestSchema,
    response: approachesResponseSchema,
    class: "light",
    cacheable: true,
  },

  sessionsCreate: {
    method: "POST",
    path: "/sessions",
    body: createSessionRequestSchema,
    response: sessionSummarySchema,
    class: "light",
  },
  sessionsList: {
    method: "GET",
    path: "/sessions",
    response: z.array(sessionSummarySchema),
    class: "light",
  },
  sessionGet: {
    method: "GET",
    path: "/sessions/{id}",
    response: sessionStateSchema,
    class: "light",
  },
  sessionPatch: {
    method: "PATCH",
    path: "/sessions/{id}",
    body: patchSessionRequestSchema,
    response: sessionSummarySchema,
    class: "light",
  },

  concept: {
    method: "POST",
    path: "/sessions/{id}/concept",
    response: z.object({ session_id: z.string(), card: conceptCardSchema }),
    class: "heavy",
    cacheable: true,
  },
  conceptSimplify: {
    method: "POST",
    path: "/sessions/{id}/concept/simplify",
    response: z.object({ session_id: z.string(), simplified: simplifiedConceptSchema }),
    class: "heavy",
    cacheable: true,
  },

  microQuestions: {
    method: "POST",
    path: "/sessions/{id}/micro-questions",
    response: generateQuestionsResponseSchema,
    class: "heavy",
    idempotent: true,
    // Deliberately NOT locally cacheable: question credits are charged even when
    // the server serves a cached plan (§15.8). Skipping the request would let a
    // learner generate for free by reloading the page.
  },
  microQuestionCurrent: {
    method: "GET",
    path: "/sessions/{id}/micro-questions/current",
    response: currentQuestionSchema,
    class: "light",
  },
  microQuestionHint: {
    method: "POST",
    path: "/sessions/{id}/micro-questions/{k}/hint",
    response: hintResponseSchema,
    class: "light",
  },
  microQuestionAnswer: {
    method: "POST",
    path: "/sessions/{id}/micro-questions/{k}/answer",
    body: answerSubmissionSchema,
    response: answerResponseSchema,
    class: "check",
  },

  checklist: {
    method: "GET",
    path: "/sessions/{id}/checklist",
    response: checklistApiSchema,
    class: "light",
  },

  analysis: {
    method: "POST",
    path: "/sessions/{id}/analysis",
    body: analysisRequestSchema,
    response: analysisResponseSchema,
    class: "analysis",
    idempotent: true,
    cacheable: true,
  },

  usage: { method: "GET", path: "/usage", response: usageSchema, class: "light" },
  progress: { method: "GET", path: "/progress", response: progressSchema, class: "light" },
  mistakes: {
    method: "GET",
    path: "/mistakes",
    response: z.object({ items: z.array(mistakeEntrySchema), has_more: z.boolean() }),
    class: "light",
  },
  reviewQueue: {
    method: "GET",
    path: "/review-queue",
    response: z.object({ items: z.array(reviewItemSchema) }),
    class: "light",
  },
  savedCards: {
    method: "GET",
    path: "/saved-cards",
    response: z.object({ items: z.array(savedCardSchema) }),
    class: "light",
  },
  events: {
    method: "POST",
    path: "/events",
    body: z.object({
      events: z
        .array(
          z.object({
            name: z.string().max(60),
            props: z.record(z.string(), z.unknown()).default({}),
          }),
        )
        .min(1)
        .max(50),
    }),
    response: z.object({ accepted: z.number().int().min(0) }),
    class: "light",
    idempotent: true,
  },
} as const;

export type RouteId = keyof typeof ROUTES;
export type RouteDef = (typeof ROUTES)[RouteId];
export type RouteClass = RouteDef["class"];

export type ResponseOf<R extends RouteId> = z.infer<(typeof ROUTES)[R]["response"]>;
export type BodyOf<R extends RouteId> =
  (typeof ROUTES)[R] extends { body: z.ZodTypeAny } ? z.infer<(typeof ROUTES)[R]["body"]> : never;

/** Funnel events (§22.4). Every write is idempotency-keyed. */
export const EVENT_NAMES = [
  "problem_detected",
  "approaches_shown",
  "approach_selected",
  "concept_viewed",
  "simplify_clicked",
  "mq_generated",
  "mq_answered",
  "hint_used",
  "question_revealed",
  "checklist_reached",
  "checklist_revealed",
  "analysis_opened",
  "session_completed",
  "credits_exhausted_seen",
] as const;
export type EventName = (typeof EVENT_NAMES)[number];