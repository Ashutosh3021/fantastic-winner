import { z } from "zod";
import { analysisConfidenceSchema, complexityClassSchema, isoDate } from "./common";
import { analysisTraceSpecSchema } from "./diagram";

export const analysisRequestSchema = z.object({
  code: z.string().min(1).max(20_000),
  /** Language id reported by the editor bridge. Wins over the preference. */
  editor_language: z.string().max(40),
  /** Fallback used only when the bridge failed or both agree. */
  language: z.string().max(40).optional(),
});
export type AnalysisRequest = z.infer<typeof analysisRequestSchema>;

export const complexityChartSchema = z.object({
  time_class: complexityClassSchema,
  space_class: z.string().min(1).max(40),
  confidence: analysisConfidenceSchema,
  n_max: z.number().min(1),
  n_max_source: z.enum(["constraints", "assumed"]),
  brute_force_class: z.string().max(40).nullable().default(null),
  budget_ops: z.number().positive(),
  /** True when the AI estimate and the static heuristic disagreed (§13.1.2). */
  estimated: z.boolean().default(false),
});
export type ComplexityChart = z.infer<typeof complexityChartSchema>;

export const codeExplanationSchema = z.object({
  label: z.string().min(1).max(80),
  quote: z.string().max(400),
  why: z.string().min(1).max(600),
});

export const analysisResponseSchema = z.object({
  session_id: z.string(),
  time_class: complexityClassSchema,
  space_class: z.string().min(1).max(40),
  complexity_explanation: z.string().min(1),
  line_explanations: z.array(codeExplanationSchema).max(12).default([]),
  edge_cases: z.array(z.string().max(400)).max(8).default([]),
  improvement_suggestions: z.array(z.string().max(400)).max(8).default([]),
  related_tricks: z.array(z.string().max(400)).max(6).default([]),
  better_approach: z
    .object({
      approach_id: z.string(),
      summary: z.string().max(800),
      complexity: z.string().max(40).nullable().default(null),
    })
    .nullable()
    .default(null),
  chart: complexityChartSchema,
  trace: analysisTraceSpecSchema.nullable().default(null),
  editor_language: z.string().max(40),
  language_mismatch: z.boolean().default(false),
  analyzed_at: isoDate,
});
export type AnalysisResponse = z.infer<typeof analysisResponseSchema>;