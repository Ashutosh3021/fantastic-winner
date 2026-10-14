/**
 * Layout engines, one per `kind` (§12.3).
 *
 * Every layout is pure and deterministic: same spec + same frame → same
 * geometry, every render. Graph layouts seed a fixed initial arrangement and run
 * a fixed number of simulation ticks synchronously, so a cached spec always
 * draws identically.
 */

import { hierarchy } from "d3-hierarchy";
import {
  forceCenter,
  forceLink,
  forceManyBody,
  forceSimulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";

import type { DiagramKind, LearningDiagramSpec } from "../schemas";
import {
  fit,
  highlightFill,
  rangeFill,
  type PanelNode,
  type Scene,
  type SceneNode,
} from "./scene";

const M = { pad: 12, cell: 38, cellH: 34, gap: 6, pointerGap: 26, annotGap: 20 };

/* ------------------------------------------------------------------ helpers */

function panel(x: number, y: number, w: number, items: string[], title: string): PanelNode {
  const rowH = 18;
  const h = 26 + items.length * rowH;
  return { kind: "panel", x, y, w, h, title, items };
}

function baseScene(width: number, height: number, nodes: SceneNode[]): Scene {
  return { width: Math.max(1, width), height: Math.max(1, height), nodes };
}

function clampIndex(index: number, length: number): number {
  if (length <= 0) return 0;
  return Math.min(Math.max(index, 0), length - 1);
}

/* --------------------------------------------------------------- grid/table */

type Cell = { x: number; y: number; w: number; h: number };

function buildGrid(
  rows: string[][],
  originX: number,
  originY: number,
  cellW: number,
  cellH: number,
): { cells: Cell[]; cols: number } {
  const cells: Cell[] = [];
  rows.forEach((row, r) => {
    row.forEach((_value, c) => {
      cells.push({
        x: originX + c * cellW,
        y: originY + r * cellH,
        w: cellW,
        h: cellH,
      });
    });
  });
  return { cells, cols: Math.max(1, ...rows.map((r) => r.length)) };
}

/* ---------------------------------------------------------- array_pointers */

function frameOf(spec: LearningDiagramSpec, frameIndex: number) {
  const index = clampIndex(frameIndex, spec.frames.length);
  return spec.frames[index]!;
}

function layoutArrayPointers(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "array_pointers") return { width: 1, height: 1, nodes: [] };
  const cells = spec.data.cells;
  const frame = frameOf(spec, frameIndex);
  const cellW = M.cell;
  const n = cells.length;
  const labelW = Math.max(48, ...frame.pointers.map((p) => p.label.length * 7 + 14));

  const arrayY = M.pad + M.pointerGap;
  const gridW = n * cellW;
  const nodes: SceneNode[] = [];

  const panelNode = frame.side_panel
    ? panel(gridW + M.pad * 2, M.pad, labelW + 46, frame.side_panel.items, frame.side_panel.title)
    : null;
  const width = Math.max(gridW + M.pad * 2, (panelNode?.x ?? 0) + (panelNode?.w ?? 0) + M.pad);

  // Range bands above the array.
  for (const range of frame.ranges) {
    const from = clampIndex(Math.min(range.from, range.to), n);
    const to = clampIndex(Math.max(range.from, range.to), n);
    const x = M.pad + from * cellW;
    const w = (to - from + 1) * cellW;
    nodes.push({
      kind: "rect",
      x,
      y: arrayY - 12,
      w,
      h: M.cellH + 24,
      rx: 8,
      fill: rangeFill(range.style),
      stroke: range.style === "invalid" ? "accent" : "line",
      opacity: range.style === "plain" ? 0.6 : 1,
    });
  }

  // Cells.
  const highlightByIndex = new Map(frame.highlights.map((h) => [h.index, h.style]));
  const annotationByIndex = new Map(frame.annotations.map((a) => [a.index, a.text]));

  cells.forEach((value, index) => {
    const highlight = highlightByIndex.get(index);
    nodes.push({
      kind: "rect",
      x: M.pad + index * cellW,
      y: arrayY,
      w: cellW,
      h: M.cellH,
      rx: 6,
      fill: highlight ? highlightFill(highlight) : "cell",
      stroke: "line",
      label: fit(value, 4),
      labelSize: 12,
      labelRole: "text",
    });
    const annotation = annotationByIndex.get(index);
    if (annotation) {
      nodes.push({
        kind: "text",
        x: M.pad + index * cellW + cellW / 2,
        y: arrayY + M.cellH + M.annotGap,
        text: fit(annotation, 10),
        size: 10,
        anchor: "middle",
        role: "textMuted",
      });
    }
  });

  // Pointer markers below the array.
  frame.pointers.forEach((pointer, order) => {
    const index = clampIndex(pointer.index, n);
    const cx = M.pad + index * cellW + cellW / 2;
    const y = arrayY + M.cellH + 12 + order * M.pointerGap;
    nodes.push({
      kind: "line",
      x1: cx,
      y1: arrayY + M.cellH + 2,
      x2: cx,
      y2: y,
      stroke: "accent",
      width: 1.5,
      marker: "arrow",
    });
    nodes.push({
      kind: "text",
      x: cx,
      y: y + 12,
      text: pointer.label,
      size: 11,
      anchor: "middle",
      role: "accent",
      weight: 600,
    });
  });

  const height =
    arrayY + M.cellH + 16 + Math.max(1, frame.pointers.length) * M.pointerGap + M.pad;

  if (panelNode) nodes.push(panelNode);
  return baseScene(width, height, nodes);
}

/* -------------------------------------------------------------- grid family */

function layoutGrid(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "grid") return { width: 1, height: 1, nodes: [] };
  const rows = spec.data.rows;
  const frame = frameOf(spec, frameIndex);
  const cellW = M.cell;
  const cellH = M.cellH;
  const cols = Math.max(1, ...rows.map((r) => r.length));
  const { cells } = buildGrid(rows, M.pad, M.pad, cellW, cellH);

  const highlightByIndex = new Map(frame.highlights.map((h) => [h.index, h.style]));
  const rangeByRow = new Map(frame.ranges.map((r) => [r.to, r.style]));

  const nodes: SceneNode[] = cells.map((cell, index) => {
    const row = Math.floor(index / cols);
    const rangeStyle = rangeByRow.get(row);
    const highlight = highlightByIndex.get(index);
    return {
      kind: "rect" as const,
      x: cell.x,
      y: cell.y,
      w: cell.w,
      h: cell.h,
      rx: 4,
      fill: highlight ? highlightFill(highlight) : rangeStyle ? rangeFill(rangeStyle) : "cell",
      stroke: "line",
      label: fit(rows[row]?.[index % cols] ?? "", 4),
      labelSize: 12,
      labelRole: "text" as const,
    };
  });

  return baseScene(cols * cellW + M.pad * 2, rows.length * cellH + M.pad * 2, nodes);
}

function layoutTable(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "dp_table" && spec.kind !== "hashmap_table") {
    return { width: 1, height: 1, nodes: [] };
  }
  const { columns, rows } = spec.data;
  const frame = frameOf(spec, frameIndex);
  const cellW = Math.max(44, Math.min(72, 260 / Math.max(1, columns.length)));
  const cellH = 30;
  const nodes: SceneNode[] = [];

  columns.forEach((name, c) => {
    nodes.push({
      kind: "rect",
      x: M.pad + c * cellW,
      y: M.pad,
      w: cellW,
      h: cellH,
      rx: 4,
      fill: "surface",
      stroke: "line",
      label: fit(name, 8),
      labelSize: 11,
      labelRole: "textMuted",
    });
  });

  const rangeByRow = new Map(frame.ranges.map((r) => [r.from, r.style]));
  const highlightByIndex = new Map(frame.highlights.map((h) => [h.index, h.style]));

  rows.forEach((row, r) => {
    row.forEach((value, c) => {
      const index = r * columns.length + c;
      const highlight = highlightByIndex.get(index);
      const rangeStyle = rangeByRow.get(r);
      nodes.push({
        kind: "rect",
        x: M.pad + c * cellW,
        y: M.pad + (r + 1) * cellH,
        w: cellW,
        h: cellH,
        rx: 4,
        fill: highlight ? highlightFill(highlight) : rangeStyle ? rangeFill(rangeStyle) : "cell",
        stroke: "line",
        label: fit(value, 8),
        labelSize: 12,
        labelRole: "text",
      });
    });
  });

  const width = columns.length * cellW + M.pad * 2;
  const height = (rows.length + 1) * cellH + M.pad * 2;
  return baseScene(width, height, nodes);
}

/* -------------------------------------------------------------- stack_queue */

function layoutSlots(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "stack_queue") return { width: 1, height: 1, nodes: [] };
  const { slots, orientation, label } = spec.data;
  const frame = frameOf(spec, frameIndex);
  const highlightByIndex = new Map(frame.highlights.map((h) => [h.index, h.style]));
  const cell = 46;
  const gap = 6;
  const nodes: SceneNode[] = [];
  const headerH = label ? 20 : 0;

  if (label) {
    nodes.push({
      kind: "text",
      x: M.pad,
      y: M.pad + 12,
      text: label,
      size: 11,
      role: "textMuted",
      weight: 600,
    });
  }

  slots.forEach((value, i) => {
    const highlight = highlightByIndex.get(i);
    const x =
      orientation === "horizontal"
        ? M.pad + i * (cell + gap)
        : M.pad;
    const y =
      orientation === "horizontal"
        ? M.pad + headerH
        : M.pad + headerH + i * (cell + gap);
    nodes.push({
      kind: "rect",
      x,
      y,
      w: cell,
      h: cell,
      rx: 6,
      fill: highlight ? highlightFill(highlight) : "cell",
      stroke: "line",
      label: fit(value, 5),
      labelSize: 13,
      labelRole: "text",
    });
  });

  const span = slots.length * (cell + gap);
  const width = orientation === "horizontal" ? span + M.pad * 2 : cell + M.pad * 2;
  const height =
    orientation === "horizontal"
      ? headerH + cell + M.pad * 2
      : headerH + span + M.pad * 2;

  return baseScene(width, height, nodes);
}

/* -------------------------------------------------------------- intervals */

function layoutIntervals(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "intervals") return { width: 1, height: 1, nodes: [] };
  const frame = frameOf(spec, frameIndex);
  const rows = spec.data.rows;
  const axisMax = Math.max(1, ...rows.map((r) => r.end));
  const labelW = 42;
  const plotW = 240;
  const rowH = 30;
  const scale = (value: number) => labelW + (value / axisMax) * plotW;

  const nodes: SceneNode[] = [
    { kind: "line", x1: labelW, y1: M.pad + 4, x2: labelW + plotW, y2: M.pad + 4, stroke: "lineStrong" },
    {
      kind: "text",
      x: labelW,
      y: M.pad + 16,
      text: "0",
      size: 10,
      role: "textMuted",
    },
    {
      kind: "text",
      x: labelW + plotW,
      y: M.pad + 16,
      text: String(axisMax),
      size: 10,
      anchor: "end",
      role: "textMuted",
    },
  ];

  rows.forEach((row, r) => {
    const y = M.pad + 30 + r * rowH;
    const highlight = frame.highlights.find((h) => h.index === r);
    nodes.push({
      kind: "text",
      x: 0,
      y: y + 16,
      text: fit(row.label, 6),
      size: 11,
      role: "textMuted",
    });
    nodes.push({
      kind: "rect",
      x: scale(row.start),
      y,
      w: Math.max(6, scale(row.end) - scale(row.start)),
      h: 22,
      rx: 5,
      fill: highlight ? highlightFill(highlight.style) : "windowBand",
      stroke: "line",
    });
  });

  return baseScene(labelW + plotW + M.pad, M.pad + 34 + rows.length * rowH, nodes);
}

/* -------------------------------------------------------------- flow_steps */

function layoutFlowSteps(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "flow_steps") return { width: 1, height: 1, nodes: [] };
  const frame = frameOf(spec, frameIndex);
  const steps = spec.data.steps;
  const boxW = 190;
  const boxH = 40;
  const gapY = 22;
  const nodes: SceneNode[] = [];
  const highlight = new Set(frame.highlights.map((h) => h.index));

  steps.forEach((step, i) => {
    const y = M.pad + i * (boxH + gapY);
    nodes.push({
      kind: "rect",
      x: M.pad,
      y,
      w: boxW,
      h: boxH,
      rx: 8,
      fill: highlight.has(i) ? "cellActive" : "cell",
      stroke: "line",
      label: fit(step, 24),
      labelSize: 12,
      labelRole: "text",
    });
    if (i < steps.length - 1) {
      const cx = M.pad + boxW / 2;
      nodes.push({
        kind: "line",
        x1: cx,
        y1: y + boxH,
        x2: cx,
        y2: y + boxH + gapY,
        stroke: "lineStrong",
        width: 1.5,
        marker: "arrow",
      });
    }
  });

  const frameNode = frame.side_panel
    ? panel(M.pad * 2 + boxW, M.pad, 140, frame.side_panel.items, frame.side_panel.title)
    : null;
  if (frameNode) nodes.push(frameNode);

  return baseScene(
    (frameNode ? frameNode.x + frameNode.w + M.pad : boxW + M.pad * 2),
    M.pad + steps.length * (boxH + gapY),
    nodes,
  );
}

/* ------------------------------------------------------- node-and-edge kinds */

type NodeDatum = SimulationNodeDatum & { id: string; label: string; x: number; y: number };

function toGraph(spec: {
  data: { nodes: { id: string; label: string }[]; edges: { from: string; to: string; label?: string }[] };
}): { nodes: NodeDatum[]; links: SimulationLinkDatum<NodeDatum>[] } {
  const nodes: NodeDatum[] = spec.data.nodes.map((n, i) => ({
    id: n.id,
    label: n.label,
    // Deterministic seed: a ring, so the simulation starts from a stable shape.
    x: Math.cos((2 * Math.PI * i) / Math.max(1, spec.data.nodes.length)) * 90,
    y: Math.sin((2 * Math.PI * i) / Math.max(1, spec.data.nodes.length)) * 90,
  }));
  const known = new Set(nodes.map((n) => n.id));
  const links: SimulationLinkDatum<NodeDatum>[] = spec.data.edges
    .filter((e) => known.has(e.from) && known.has(e.to))
    .map((e) => ({ source: e.from, target: e.to }));

  const simulation = forceSimulation<NodeDatum>(nodes)
    .force(
      "link",
      forceLink<NodeDatum, SimulationLinkDatum<NodeDatum>>(links)
        .id((d) => d.id)
        .distance(70)
        .strength(0.8),
    )
    .force("charge", forceManyBody().strength(-180))
    .force("center", forceCenter(0, 0))
    .stop();

  // Fixed tick count: the same spec always produces the same picture.
  simulation.tick(120);
  return { nodes, links };
}

function drawEdges(
  positions: Map<string, { x: number; y: number }>,
  edges: { from: string; to: string; label?: string }[],
  nodes: SceneNode[],
  nodeW: number,
): void {
  for (const edge of edges) {
    const a = positions.get(edge.from);
    const b = positions.get(edge.to);
    if (!a || !b) continue;
    nodes.push({
      kind: "line",
      x1: a.x,
      y1: a.y,
      x2: b.x,
      y2: b.y,
      stroke: "lineStrong",
      width: 1.4,
      marker: "arrow",
    });
    if (edge.label) {
      nodes.push({
        kind: "text",
        x: (a.x + b.x) / 2,
        y: (a.y + b.y) / 2 - 4,
        text: fit(edge.label, 8),
        size: 10,
        anchor: "middle",
        role: "textMuted",
      });
    }
  }
  void nodeW;
}

function layoutGraph(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "graph") return { width: 1, height: 1, nodes: [] };
  const frame = frameOf(spec, frameIndex);
  const { nodes: simulated, links } = toGraph(spec);
  const nodeW = 54;
  const nodeH = 30;
  const visited = new Set(frame.highlights.map((h) => h.index));
  const positions = new Map(simulated.map((n) => [n.id, { x: n.x, y: n.y }]));

  const nodes: SceneNode[] = [];
  drawEdges(positions, spec.data.edges, nodes, nodeW);

  const radius = 150;
  simulated.forEach((node, index) => {
    nodes.push({
      kind: "rect",
      x: node.x - nodeW / 2,
      y: node.y - nodeH / 2,
      w: nodeW,
      h: nodeH,
      rx: 15,
      fill: visited.has(index) ? "cellActive" : "cell",
      stroke: "line",
      label: fit(node.label || node.id, 6),
      labelSize: 11,
      labelRole: "text",
    });
  });
  void links;

  return baseScene(radius * 2, radius * 2, nodes.map((n) => offset(n, radius, radius)));
}

function layoutTreeLike(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "tree" && spec.kind !== "recursion_tree") {
    return { width: 1, height: 1, nodes: [] };
  }
  const frame = frameOf(spec, frameIndex);

  interface TreeNode {
    id: string;
    label: string;
    children: TreeNode[];
  }
  const ids = spec.data.nodes.map((n) => n.id);
  const childIds = new Set(spec.data.edges.map((e) => e.to));
  const roots = ids.filter((id) => !childIds.has(id));

  const build = (id: string, seen: Set<string>): TreeNode => {
    const meta = spec.data.nodes.find((n) => n.id === id);
    const node: TreeNode = { id, label: meta?.label ?? id, children: [] };
    if (seen.has(id)) return node;
    seen.add(id);
    for (const edge of spec.data.edges) {
      if (edge.from === id) node.children.push(build(edge.to, seen));
    }
    return node;
  };

  const trees: TreeNode[] = (roots.length > 0 ? roots : ids.slice(0, 1)).map((id) =>
    build(id, new Set()),
  );

  const point = hierarchy<TreeNode>({ id: "__root__", label: "", children: trees })
    .sum(() => 1)
    .sort((a, b) => (a.x ?? 0) - (b.x ?? 0));

  const colW = 58;
  const rowH = 52;
  const depth = point.height + 1;
  const width = Math.max(120, (point.leaves().length + 1) * colW);
  const height = depth * rowH;

  const positions = new Map<string, { x: number; y: number }>();
  point.each((node) => {
    positions.set(node.data.id, {
      x: (node.x ?? 0) * colW + colW / 2,
      y: (node.depth + 1) * rowH,
    });
  });

  const nodes: SceneNode[] = [];
  point.links().forEach((link) => {
    const a = positions.get(link.source.data.id);
    const b = positions.get(link.target.data.id);
    if (!a || !b) return;
    nodes.push({
      kind: "line",
      x1: a.x,
      y1: a.y + 14,
      x2: b.x,
      y2: b.y - 14,
      stroke: "lineStrong",
      width: 1.3,
      marker: "arrow",
    });
  });

  const highlighted = new Set(frame.highlights.map((h) => h.index));
  point.descendants().forEach((node, index) => {
    if (!node.data.id || node.data.id === "__root__") return;
    const at = positions.get(node.data.id);
    if (!at) return;
    nodes.push({
      kind: "rect",
      x: at.x - 22,
      y: at.y - 14,
      w: 44,
      h: 28,
      rx: 14,
      fill: highlighted.has(index) ? "cellActive" : "cell",
      stroke: "line",
      label: fit(node.data.label || node.data.id, 5),
      labelSize: 11,
      labelRole: "text",
    });
  });

  return baseScene(width, height, nodes);
}

function layoutLinkedList(spec: LearningDiagramSpec, frameIndex: number): Scene {
  if (spec.kind !== "linked_list") return { width: 1, height: 1, nodes: [] };
  const frame = frameOf(spec, frameIndex);
  const nodeW = 46;
  const gap = 28;
  const nodeH = 32;
  const positions = new Map<string, { x: number; y: number }>();
  spec.data.nodes.forEach((node, index) => {
    positions.set(node.id, { x: M.pad + index * (nodeW + gap), y: M.pad + 26 });
  });

  const nodes: SceneNode[] = [];
  drawEdges(positions, spec.data.edges, nodes, nodeW);

  const highlighted = new Set(frame.highlights.map((h) => h.index));
  spec.data.nodes.forEach((node, index) => {
    const at = positions.get(node.id)!;
    nodes.push({
      kind: "rect",
      x: at.x,
      y: at.y,
      w: nodeW,
      h: nodeH,
      rx: 6,
      fill: highlighted.has(index) ? "cellActive" : "cell",
      stroke: "line",
      label: fit(node.label || node.id, 5),
      labelSize: 12,
      labelRole: "text",
    });
  });

  const sidePanel = frame.side_panel
    ? panel(positions.size * (nodeW + gap) + M.pad, M.pad, 140, frame.side_panel.items, frame.side_panel.title)
    : null;
  if (sidePanel) nodes.push(sidePanel);

  return baseScene(
    (sidePanel ? sidePanel.x + sidePanel.w + M.pad : positions.size * (nodeW + gap) + M.pad),
    M.pad + 70,
    nodes,
  );
}

function offset(node: SceneNode, dx: number, dy: number): SceneNode {
  const shift = (n: SceneNode): SceneNode => {
    switch (n.kind) {
      case "rect":
      case "panel":
        return { ...n, x: n.x + dx, y: n.y + dy };
      case "text":
        return { ...n, x: n.x + dx, y: n.y + dy };
      case "line":
        return { ...n, x1: n.x1 + dx, y1: n.y1 + dy, x2: n.x2 + dx, y2: n.y2 + dy };
      case "bracket":
        return { ...n, x: n.x + dx, y: n.y + dy };
    }
  };
  return shift(node);
}

/* ----------------------------------------------------------------- dispatch */

export function layoutScene(spec: LearningDiagramSpec, frameIndex: number): Scene {
  switch (spec.kind) {
    case "array_pointers":
      return layoutArrayPointers(spec, frameIndex);
    case "grid":
      return layoutGrid(spec, frameIndex);
    case "dp_table":
    case "hashmap_table":
      return layoutTable(spec, frameIndex);
    case "stack_queue":
      return layoutSlots(spec, frameIndex);
    case "intervals":
      return layoutIntervals(spec, frameIndex);
    case "flow_steps":
      return layoutFlowSteps(spec, frameIndex);
    case "graph":
      return layoutGraph(spec, frameIndex);
    case "tree":
    case "recursion_tree":
      return layoutTreeLike(spec, frameIndex);
    case "linked_list":
      return layoutLinkedList(spec, frameIndex);
  }
}

export const SUPPORTED_KINDS: DiagramKind[] = [
  "array_pointers",
  "grid",
  "dp_table",
  "hashmap_table",
  "stack_queue",
  "intervals",
  "flow_steps",
  "graph",
  "tree",
  "recursion_tree",
  "linked_list",
];