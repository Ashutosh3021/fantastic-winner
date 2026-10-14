import { z } from "zod";
import { approachIdSchema } from "./common";

export const approachSchema = z.object({
  id: approachIdSchema,
  name: z.string(),
  confidence: z.number().min(0).max(1),
  simple_reason: z.string(),
  when_to_use: z.string(),
  difficulty_for_beginner: z.enum(["easy", "medium", "hard"]),
  expected_complexity: z.string().nullable().default(null),
});
export type Approach = z.infer<typeof approachSchema>;

export const approachesResponseSchema = z.object({
  problem_type: z.string(),
  target_complexity_hint: z.string().nullable().default(null),
  approaches: z.array(approachSchema),
  recommended_first: approachIdSchema,
});
export type ApproachesResponse = z.infer<typeof approachesResponseSchema>;