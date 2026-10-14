import { describe, expect, it } from "vitest";

import { learningDiagramSpecSchema, type LearningDiagramSpec } from "../src/schemas";
import { layoutScene } from "../src/diagrams/layout";
import { toAscii } from "../src/diagrams/ascii";
import type { SceneNode } from "../src/diagrams/scene";

const slidingWindow = {
  kind: "array_pointers",
  title: "A window sliding over a small string",
  alt_text: "Five letters a b c a b with a bracket around the first three.",
  data: { cells: ["a", "b", "c", "a", "b"], cell_type: "char" },
  frames: [
    {
      caption: "Start: the window holds just the first letter.",
      pointers: [
        { id: "L", index: 0, label: "left" },
        { id: "R", index: 0, label: "right" },
      ],
      ranges: [{ from: 0, to: 0, style: "window" }],
      highlights: [],
      annotations: [{ index: 0, text: "new" }],
      side_panel: { type: "set", title: "letters in window", items: ["a"] },
    },
    {
      caption: "Grow right while every letter is new.",
      pointers: [
        { id: "L", index: 0, label: "left" },
        { id: "R", index: 2, label: "right" },
      ],
      ranges: [{ from: 0, to: 2, style: "window" }],
      highlights: [],
      annotations: [],
      side_panel: { type: "set", title: "letters in window", items: ["a", "b", "c"] },
    },
  ],
} as const satisfies LearningDiagramSpec;

function spec(overrides: Partial<LearningDiagramSpec> = {}): LearningDiagramSpec {
  return { ...slidingWindow, ...overrides } as LearningDiagramSpec;
}

function coordinates(node: SceneNode): number[] {
  switch (node.kind) {
    case "rect":
    case "text":
    case "panel":
    case "bracket":
      return [node.x, node.y];
    case "line":
      return [node.x1, node.y1, node.x2, node.y2];
  }
}

describe("learningDiagramSpecSchema", () => {
  it("accepts a well-formed spec", () => {
    expect(learningDiagramSpecSchema.safeParse(slidingWindow).success).toBe(true);
  });

  it("rejects a spec carrying reveals_solution — the field does not exist", () => {
    // §12.5: the capability has to be unreachable from the learning path, not
    // merely guarded by a validator someone forgot to write.
    const parsed = learningDiagramSpecSchema.safeParse({
      ...slidingWindow,
      reveals_solution: true,
    });
    expect(parsed.success).toBe(false);
  });

  it("rejects an unknown kind", () => {
    expect(
      learningDiagramSpecSchema.safeParse({ ...slidingWindow, kind: "hand_drawn" }).success,
    ).toBe(false);
  });

  it("rejects an unknown property anywhere in the spec", () => {
    expect(
      learningDiagramSpecSchema.safeParse({ ...slidingWindow, colour: "red" }).success,
    ).toBe(false);
  });

  it("rejects a caption over the length cap", () => {
    expect(
      learningDiagramSpecSchema.safeParse({
        ...slidingWindow,
        frames: [{ ...slidingWindow.frames[0], caption: "x".repeat(121) }],
      }).success,
    ).toBe(false);
  });

  it("rejects more than six frames", () => {
    expect(
      learningDiagramSpecSchema.safeParse({
        ...slidingWindow,
        frames: Array.from({ length: 7 }, () => slidingWindow.frames[0]),
      }).success,
    ).toBe(false);
  });

  it("rejects more than twelve data items", () => {
    expect(
      learningDiagramSpecSchema.safeParse({
        ...slidingWindow,
        data: { cells: Array.from({ length: 13 }, (_, i) => `x${i}`), cell_type: "char" },
      }).success,
    ).toBe(false);
  });
});

describe("layoutScene", () => {
  it("produces the same geometry for the same spec and frame", () => {
    // Deterministic output is what makes cached specs safe to render (§12.7).
    expect(JSON.stringify(layoutScene(spec(), 0))).toBe(
      JSON.stringify(layoutScene(spec(), 0)),
    );
  });

  it("keeps every node inside the declared scene box", () => {
    const scene = layoutScene(spec(), 0);
    for (const node of scene.nodes) {
      for (const value of coordinates(node)) {
        expect(Number.isFinite(value)).toBe(true);
        expect(value).toBeGreaterThanOrEqual(-1);
        expect(value).toBeLessThanOrEqual(Math.max(scene.width, scene.height) + 1);
      }
    }
  });

  it("clamps an out-of-range pointer index instead of throwing", () => {
    const clamped = spec({
      frames: [
        {
          ...slidingWindow.frames[0],
          pointers: [{ id: "R", index: 99, label: "right" }],
        },
      ],
    });
    expect(() => layoutScene(clamped, 0)).not.toThrow();
  });

  it("clamps an out-of-range frame index", () => {
    expect(() => layoutScene(spec(), 99)).not.toThrow();
    expect(layoutScene(spec(), 99).width).toBeGreaterThan(0);
  });

  it("draws every pointer the frame asks for", () => {
    const scene = layoutScene(spec(), 1);
    const labels = scene.nodes
      .filter((node) => node.kind === "text")
      .map((node) => (node as { text: string }).text);
    expect(labels).toContain("left");
    expect(labels).toContain("right");
  });

  it("labels the cells it was given", () => {
    const scene = layoutScene(spec(), 0);
    const cellLabels = scene.nodes
      .filter((node) => node.kind === "rect")
      .map((node) => (node as { label?: string }).label)
      .filter(Boolean);
    expect(cellLabels).toEqual(expect.arrayContaining(["a", "b", "c"]));
  });

  it("renders every diagram kind without throwing", () => {
    const kinds = {
      array_pointers: { cells: ["a", "b"], cell_type: "char" },
      dp_table: { columns: ["i", "j"], rows: [["0", "1"]] },
      grid: { rows: [["1", "0"], ["0", "1"]] },
      hashmap_table: { columns: ["key", "value"], rows: [["a", "0"]] },
      stack_queue: { slots: ["a", "b"], orientation: "vertical" as const },
      linked_list: {
        nodes: [{ id: "a", label: "1" }, { id: "b", label: "2" }],
        edges: [{ from: "a", to: "b" }],
      },
      tree: {
        nodes: [{ id: "r", label: "r" }, { id: "l", label: "l" }],
        edges: [{ from: "r", to: "l" }],
      },
      recursion_tree: {
        nodes: [{ id: "r", label: "f" }],
        edges: [],
      },
      graph: {
        nodes: [{ id: "a", label: "a" }, { id: "b", label: "b" }],
        edges: [{ from: "a", to: "b" }],
      },
      intervals: { labels: [], rows: [{ label: "job", start: 1, end: 4 }] },
      flow_steps: { steps: ["read", "write"] },
    } as const;

    for (const [kind, data] of Object.entries(kinds)) {
      const candidate = learningDiagramSpecSchema.safeParse({
        kind,
        data,
        title: "t",
        alt_text: "a",
        frames: [
          {
            caption: "c",
            pointers: [],
            ranges: [],
            highlights: [],
            annotations: [],
          },
        ],
      });
      expect(candidate.success, `${kind} should validate`).toBe(true);
      if (!candidate.success) continue;
      const scene = layoutScene(candidate.data, 0);
      expect(scene.width, `${kind} should have width`).toBeGreaterThan(0);
      expect(scene.nodes.length, `${kind} should draw something`).toBeGreaterThan(0);
    }
  });
});

describe("toAscii", () => {
  it("renders a readable fallback with one marker row per pointer", () => {
    const art = toAscii(spec(), 0);
    const [left, right, cells] = art.split("\n");
    expect(left?.trim()).toBe("left");
    expect(right?.trim()).toBe("right");
    expect(cells).toBe("[a ] [b ] [c ] [a ] [b ]");
  });

  it("survives a frame index past the end", () => {
    expect(() => toAscii(spec(), 99)).not.toThrow();
  });

  it("does not throw on any kind", () => {
    expect(() =>
      toAscii(spec({ kind: "flow_steps", data: { steps: ["one", "two"] } } as never)),
    ).not.toThrow();
  });
});