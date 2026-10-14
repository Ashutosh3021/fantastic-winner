import { z } from "zod";
import { constraintBoundSchema } from "./common";

/**
 * `ProblemData` as produced by the extraction ladder (§5.3).
 *
 * `content_hash` is a *hint* used only to detect extraction drift; the server
 * recomputes its own hash from normalised text and never keys the cache on it
 * (§5.3, §15.8).
 */
export const problemDataSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(200)
    .regex(/^[a-z0-9-]+$/, "slug must be lowercase kebab-case"),
  url: z.string().url(),
  title: z.string().min(1).max(300),
  difficulty: z.enum(["Easy", "Medium", "Hard", "Unknown"]).default("Unknown"),
  statement_text: z.string().max(20_000),
  examples: z
    .array(
      z.object({
        input: z.string(),
        output: z.string(),
        explanation: z.string().default(""),
      }),
    )
    .max(10)
    .default([]),
  constraints_text: z.string().max(5_000).default(""),
  constraint_bounds: z.array(constraintBoundSchema).max(20).default([]),
  tags: z.array(z.string().max(60)).max(20).default([]),
  editor_language: z.string().max(40).default(""),
  content_hash: z.string().max(120).optional(),
  extraction_quality: z.enum(["full", "partial", "manual"]),
});
export type ProblemData = z.infer<typeof problemDataSchema>;

/** Payload accepted by `POST /v1/problems/approaches`. */
export const approachesRequestSchema = z.object({
  problem: problemDataSchema,
});
export type ApproachesRequest = z.infer<typeof approachesRequestSchema>;