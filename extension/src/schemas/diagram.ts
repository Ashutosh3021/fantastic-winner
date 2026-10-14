import { z } from "zod";

/**
 * Diagram specs (§12).
 *
 * The AI never draws. It emits this typed spec, the backend validates it, and
 * our own renderer draws the SVG. `LearningDiagramSpec` is
 * `additionalProperties: false` on every object and deliberately has **no**
 * `reveals_solution` field, so a concept/micro-question diagram cannot carry
 * that capability even if a model emits it (§12.5). Full-trace diagrams use
 * `AnalysisTraceSpec`, which is a different type constructible only on the
 * analysis route.
 */

export const DIAGRAM_KINDS = [
  "array_pointers",
  "hashmap_table",
  "stack_queue",
  "linked_list",
  "tree",
  "graph",
  "grid",
  "dp_table",
  "intervals",
  "recursion_tree",
  "flow_steps",
] as const;
export type DiagramKind = (typeof DIAGRAM_KINDS)[number];

export const DIAGRAM_LIMITS = {
  maxItems: 12,
  maxFrames: 6,
  maxCaptionChars: 120,
  maxTitleChars: 80,
  maxAltTextChars: 400,
  maxJsonBytes: 16_000,
} as const;

const pointerSchema = z.object({
  id: z.string().min(1).max(24),
  index: z.number().int().min(0),
  label: z.string().min(1).max(24),
});

const rangeSchema = z.object({
  from: z.number().int().min(0),
  to: z.number().int().min(0),
  style: z.enum(["window", "invalid", "active", "result", "plain"]),
});

const highlightSchema = z.object({
  index: z.number().int().min(0),
  style: z.enum(["conflict", "active", "visited", "result", "muted"]),
});

const annotationSchema = z.object({
  index: z.number().int().min(0),
  text: z.string().min(1).max(60),
});

const sidePanelSchema = z.object({
  type: z.enum(["set", "map", "list", "stack", "queue", "text"]),
  title: z.string().min(1).max(40),
  items: z.array(z.string().max(40)).max(24),
});

const frameSchema = z.object({
  caption: z.string().min(1).max(DIAGRAM_LIMITS.maxCaptionChars),
  pointers: z.array(pointerSchema).max(6).default([]),
  ranges: z.array(rangeSchema).max(6).default([]),
  highlights: z.array(highlightSchema).max(24).default([]),
  annotations: z.array(annotationSchema).max(12).default([]),
  side_panel: sidePanelSchema.optional(),
});

const captionSchema = z.string().min(1).max(DIAGRAM_LIMITS.maxTitleChars);
const altTextSchema = z.string().min(1).max(DIAGRAM_LIMITS.maxAltTextChars);

const arrayDataSchema = z.object({
  cells: z.array(z.string().max(40)).min(1).max(DIAGRAM_LIMITS.maxItems),
  cell_type: z.enum(["char", "number", "mixed"]).default("char"),
});

const gridDataSchema = z.object({
  rows: z.array(z.array(z.string().max(40))).min(1).max(DIAGRAM_LIMITS.maxItems),
});

const tableDataSchema = z.object({
  columns: z.array(z.string().max(40)).min(1).max(DIAGRAM_LIMITS.maxItems),
  rows: z.array(z.array(z.string().max(40))).min(1).max(DIAGRAM_LIMITS.maxItems),
});

const slotsDataSchema = z.object({
  slots: z.array(z.string().max(40)).min(1).max(DIAGRAM_LIMITS.maxItems),
  orientation: z.enum(["horizontal", "vertical"]).default("vertical"),
  label: captionSchema.optional(),
});

const nodesDataSchema = z.object({
  nodes: z
    .array(
      z.object({
        id: z.string().min(1).max(24),
        label: z.string().max(40),
      }),
    )
    .min(1)
    .max(DIAGRAM_LIMITS.maxItems),
  edges: z
    .array(
      z.object({
        from: z.string().min(1).max(24),
        to: z.string().min(1).max(24),
        label: z.string().max(24).optional(),
      }),
    )
    .max(24)
    .default([]),
});

const intervalsDataSchema = z.object({
  labels: z.array(z.string().max(24)).max(DIAGRAM_LIMITS.maxItems),
  rows: z
    .array(
      z.object({
        label: z.string().max(24),
        start: z.number().min(0),
        end: z.number().min(0),
      }),
    )
    .min(1)
    .max(6),
});

const stepsDataSchema = z.object({
  steps: z.array(z.string().max(60)).min(1).max(DIAGRAM_LIMITS.maxItems),
});

const LEARNING_FRAMES = z.array(frameSchema).min(1).max(DIAGRAM_LIMITS.maxFrames);
const TRACE_FRAMES = z.array(frameSchema).min(1).max(24);

/**
 * Every `kind` is listed literally in both unions. Two reasons, both
 * deliberate: `z.discriminatedUnion` only infers member types from a tuple
 * literal, and the explicit list *is* the readable statement of which diagram
 * kinds CodeMentor can draw (§12.3).
 */
export const learningDiagramSpecSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("array_pointers"),
      data: arrayDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("dp_table"),
      data: tableDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("grid"),
      data: gridDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("hashmap_table"),
      data: tableDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("stack_queue"),
      data: slotsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("linked_list"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("tree"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("recursion_tree"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("graph"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("intervals"),
      data: intervalsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
  z
    .object({
      kind: z.literal("flow_steps"),
      data: stepsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: LEARNING_FRAMES,
    })
    .strict(),
]);

export type LearningDiagramSpec = z.infer<typeof learningDiagramSpecSchema>;

/**
 * The only spec type allowed to describe a full execution trace. It is never
 * reachable from concept-card or micro-question generation: `LearningDiagramSpec`
 * is `strict` and has no `reveals_solution` field at all, so a model cannot
 * smuggle one through (§12.5).
 */
export const analysisTraceSpecSchema = z.discriminatedUnion("kind", [
  z
    .object({
      kind: z.literal("array_pointers"),
      data: arrayDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("dp_table"),
      data: tableDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("grid"),
      data: gridDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("hashmap_table"),
      data: tableDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("stack_queue"),
      data: slotsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("linked_list"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("tree"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("recursion_tree"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("graph"),
      data: nodesDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("intervals"),
      data: intervalsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
  z
    .object({
      kind: z.literal("flow_steps"),
      data: stepsDataSchema,
      title: captionSchema,
      alt_text: altTextSchema,
      frames: TRACE_FRAMES,
      reveals_solution: z.literal(true),
    })
    .strict(),
]);

export type AnalysisTraceSpec = z.infer<typeof analysisTraceSpecSchema>;
export const conceptCardSchema = z.object({
  approach_id: z.string(),
  title: z.string(),
  simple_explanation: z.string(),
  why_it_fits_this_problem: z.string(),
  common_beginner_mistake: z.string(),
  humour_line: z.string().nullable().default(null),
  diagram: learningDiagramSpecSchema.nullable().default(null),
  simplified_levels_available: z.number().int().min(0).max(2),
});
export type ConceptCard = z.infer<typeof conceptCardSchema>;

export const simplifiedConceptSchema = z.object({
  level: z.number().int().min(1).max(2),
  simple_explanation: z.string(),
  why_it_fits_this_problem: z.string(),
  humour_line: z.string().nullable().default(null),
  at_max_level: z.boolean().default(false),
});
export type SimplifiedConcept = z.infer<typeof simplifiedConceptSchema>;