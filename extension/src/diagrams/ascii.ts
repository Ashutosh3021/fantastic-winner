/**
 * ASCII fallback (§12.7).
 *
 * If a spec ever fails client-side validation, or rendering throws, the card
 * still shows something readable instead of an empty box. Supports the simple
 * kinds; anything else degrades to a labelled list of the data.
 */

import type { LearningDiagramSpec } from "../schemas";

function box(value: string, width: number): string {
  const inner = width - 2;
  const text = value.length > inner ? `${value.slice(0, Math.max(1, inner - 1))}…` : value;
  return `[${text.padEnd(inner, " ")}]`;
}

export function toAscii(spec: LearningDiagramSpec, frameIndex = 0): string {
  switch (spec.kind) {
    case "array_pointers": {
      const width = 4;
      const cells = spec.data.cells.map((c) => box(c, width)).join(" ");
      const frame = spec.frames[Math.min(frameIndex, spec.frames.length - 1)];

      // One marker row per pointer, so two pointers on the same index stay
      // distinguishable instead of overprinting each other.
      const markerRows = (frame?.pointers ?? []).map((pointer) => {
        const label = pointer.label;
        const cellStart = Math.min(pointer.index, spec.data.cells.length - 1) * (width + 1);
        const pad = " ".repeat(Math.max(0, cellStart + Math.floor(width / 2) - 1));
        return `${pad}${label}`;
      });

      return [...markerRows, cells].join("\n");
    }

    case "grid":
      return spec.data.rows.map((row) => row.map((v) => box(v, 4)).join(" ")).join("\n");

    case "dp_table":
    case "hashmap_table": {
      const width = 8;
      const header = spec.data.columns.map((c) => box(c, width)).join(" ");
      const rows = spec.data.rows.map((row) =>
        row.map((v) => box(v, width)).join(" ").padEnd(spec.data.columns.length * (width + 1) - 1),
      );
      return [header, ...rows].join("\n");
    }

    case "stack_queue": {
      const slots = spec.data.slots.map((s) => box(s, 8));
      return spec.data.orientation === "horizontal" ? slots.join(" ") : slots.join("\n");
    }

    case "flow_steps":
      return spec.data.steps
        .map((step, i) => `${i + 1}. ${step}`)
        .join("\n");

    case "intervals":
      return spec.data.rows
        .map((row) => `${row.label.padEnd(6)} ${row.start} → ${row.end}`)
        .join("\n");

    case "tree":
    case "recursion_tree":
    case "graph":
    case "linked_list": {
      const edges = spec.data.edges
        .map((e) => `${e.from} → ${e.to}${e.label ? ` (${e.label})` : ""}`)
        .join("\n");
      const list = spec.data.nodes.map((n) => n.label || n.id).join(", ");
      return `Nodes: ${list}${edges ? `\n${edges}` : ""}`;
    }

    default:
      return "";
  }
}