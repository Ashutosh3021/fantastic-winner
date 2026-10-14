/**
 * Diagram scene model (§12.7).
 *
 * Layouts produce a `Scene` — a flat list of primitives — and one React SVG
 * renderer draws it. That split is what makes layouts testable, themable and
 * deterministic, and it is why no AI output ever reaches the SVG: the AI emits
 * a spec, a layout turns it into geometry, and geometry is all we draw.
 */

export type Role =
  | "surface"
  | "cell"
  | "cellActive"
  | "cellConflict"
  | "cellMuted"
  | "cellResult"
  | "windowBand"
  | "invalidBand"
  | "accent"
  | "line"
  | "lineStrong"
  | "text"
  | "textMuted"
  | "textInverse";

export type PanelNode = {
  kind: "panel";
  x: number;
  y: number;
  w: number;
  h: number;
  title: string;
  items: string[];
};

export type SceneNode =
  | {
      kind: "rect";
      x: number;
      y: number;
      w: number;
      h: number;
      rx?: number;
      fill?: Role;
      stroke?: Role;
      label?: string;
      labelSize?: number;
      labelRole?: Role;
      opacity?: number;
    }
  | {
      kind: "text";
      x: number;
      y: number;
      text: string;
      size?: number;
      anchor?: "start" | "middle" | "end";
      role?: Role;
      weight?: 400 | 500 | 600 | 700;
    }
  | {
      kind: "line";
      x1: number;
      y1: number;
      x2: number;
      y2: number;
      stroke?: Role;
      width?: number;
      dash?: string;
      marker?: "arrow";
    }
  | {
      kind: "bracket";
      x: number;
      y: number;
      w: number;
      h: number;
      stroke?: Role;
      dash?: string;
    }
  | PanelNode;

export type Scene = {
  width: number;
  height: number;
  nodes: SceneNode[];
};

/** Map a semantic style name from the spec onto a theme role (§12.4). */
export function rangeFill(style: string): Role {
  switch (style) {
    case "window":
      return "windowBand";
    case "invalid":
      return "invalidBand";
    case "active":
      return "cellActive";
    case "result":
      return "cellResult";
    default:
      return "cell";
  }
}

export function highlightFill(style: string): Role {
  switch (style) {
    case "conflict":
      return "cellConflict";
    case "active":
      return "cellActive";
    case "visited":
      return "cellMuted";
    case "result":
      return "cellResult";
    default:
      return "cell";
  }
}

/** Truncate to a pixel budget so a long token cannot blow out a cell. */
export function fit(text: string, maxChars: number): string {
  if (text.length <= maxChars) return text;
  return `${text.slice(0, Math.max(1, maxChars - 1))}…`;
}