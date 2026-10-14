import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";

import { learningDiagramSpecSchema, type LearningDiagramSpec } from "../../schemas";
import { toAscii } from "../../diagrams/ascii";
import { layoutScene } from "../../diagrams/layout";
import type { Role, SceneNode } from "../../diagrams/scene";
import { CONFIG } from "../../config";
import { cn } from "../../lib/utils";
import { Button } from "./button";
import { AppIcon, PauseIcon, PlayIcon, RepeatIcon, SkipBackIcon, SkipForwardIcon } from "../icons";

const ROLE_VAR: Record<Role, string> = {
  surface: "var(--cm-surface)",
  cell: "var(--cm-cell)",
  cellActive: "var(--cm-cell-active)",
  cellConflict: "var(--cm-cell-conflict)",
  cellMuted: "var(--cm-cell-muted)",
  cellResult: "var(--cm-cell-result)",
  windowBand: "var(--cm-window-band)",
  invalidBand: "var(--cm-invalid-band)",
  accent: "var(--cm-brand)",
  line: "var(--cm-line)",
  lineStrong: "var(--cm-line-strong)",
  text: "var(--cm-text)",
  textMuted: "var(--cm-text-muted)",
  textInverse: "var(--cm-text-inverse)",
};

type SceneProps = {
  nodes: SceneNode[];
  /**
   * Marker ids must be unique per `<svg>`; two diagrams on one page would
   * otherwise share an id and the second arrow head would disappear.
   */
  markerId: string;
};

function SceneSvg({ nodes, markerId }: SceneProps) {
  return (
    <>
      <defs>
        <marker
          id={markerId}
          viewBox="0 0 8 8"
          refX="7"
          refY="4"
          markerWidth="5"
          markerHeight="5"
          orient="auto-start-reverse"
        >
          <path d="M0,0 L8,4 L0,8 z" fill={ROLE_VAR.lineStrong} />
        </marker>
      </defs>
      {nodes.map((node, index) => {
        switch (node.kind) {
          case "rect":
            return (
              <g key={index}>
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.w}
                  height={node.h}
                  rx={node.rx ?? 6}
                  fill={ROLE_VAR[node.fill ?? "cell"]}
                  stroke={ROLE_VAR[node.stroke ?? "line"]}
                  strokeWidth={1}
                  opacity={node.opacity ?? 1}
                  className="transition-[fill,stroke,opacity] duration-[var(--duration-ui)] ease-out"
                />
                {node.label && (
                  <text
                    x={node.x + node.w / 2}
                    y={node.y + node.h / 2}
                    fontSize={node.labelSize ?? 12}
                    textAnchor="middle"
                    dominantBaseline="central"
                    fill={ROLE_VAR[node.labelRole ?? "text"]}
                  >
                    {node.label}
                  </text>
                )}
              </g>
            );
          case "text":
            return (
              <text
                key={index}
                x={node.x}
                y={node.y}
                fontSize={node.size ?? 12}
                textAnchor={node.anchor ?? "middle"}
                fill={ROLE_VAR[node.role ?? "text"]}
                fontWeight={node.weight ?? 400}
              >
                {node.text}
              </text>
            );
          case "line":
            return (
              <line
                key={index}
                x1={node.x1}
                y1={node.y1}
                x2={node.x2}
                y2={node.y2}
                stroke={ROLE_VAR[node.stroke ?? "lineStrong"]}
                strokeWidth={node.width ?? 1.2}
strokeDasharray={node.dash}
                  markerEnd={node.marker === "arrow" ? `url(#${markerId})` : undefined}
                  className="transition-[stroke,opacity] duration-[var(--duration-ui)] ease-out"
                />
            );
          case "bracket":
            return (
              <rect
                key={index}
                x={node.x}
                y={node.y}
                width={node.w}
                height={node.h}
                rx={4}
                fill="none"
                stroke={ROLE_VAR[node.stroke ?? "line"]}
                strokeDasharray={node.dash}
              />
            );
          case "panel":
            return (
              <g key={index}>
                <rect
                  x={node.x}
                  y={node.y}
                  width={node.w}
                  height={node.h}
                  rx={10}
                  fill={ROLE_VAR.surface}
                  stroke={ROLE_VAR.line}
                />
                <text x={node.x + 10} y={node.y + 17} fontSize={10} fill={ROLE_VAR.textMuted}>
                  {node.title}
                </text>
                {node.items.slice(0, 12).map((item, i) => (
                  <text
                    key={i}
                    x={node.x + 10}
                    y={node.y + 35 + i * 17}
                    fontSize={11}
                    fill={ROLE_VAR.text}
                  >
                    {item}
                  </text>
                ))}
              </g>
            );
        }
      })}
    </>
  );
}

function renderable(spec: unknown): LearningDiagramSpec | null {
  const parsed = learningDiagramSpecSchema.safeParse(spec);
  return parsed.success ? parsed.data : null;
}

/**
 * Diagram renderer + frame player (§12.7).
 *
 * The spec is re-validated with Zod on our side even though the backend already
 * validated it: a malformed payload must become a text caption, never a crash
 * inside a third-party page.
 */
export function Diagram({
  spec,
  className,
}: {
  spec: unknown;
  className?: string;
}) {
  const markerId = `${useId()}-arrow`;
  const valid = useMemo(() => renderable(spec), [spec]);
  const frameCount = valid?.frames.length ?? 0;
  const [frame, setFrame] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  useEffect(() => {
    setFrame(0);
    setPlaying(false);
  }, [valid]);

  const stop = useCallback(() => {
    setPlaying(false);
    if (timer.current) clearInterval(timer.current);
    timer.current = undefined;
  }, []);

  useEffect(() => {
    if (!playing || frameCount <= 1) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
    if (reduced) return;
    timer.current = setInterval(() => {
      setFrame((prev) => (prev + 1) % frameCount);
    }, CONFIG.frameAdvanceMs);
    return () => {
      if (timer.current) clearInterval(timer.current);
    };
  }, [playing, frameCount]);

  if (!valid) {
    return (
      <p className="text-xs text-muted-foreground">
        This diagram could not be shown, so here is the idea in words instead.
      </p>
    );
  }

  let scene: ReturnType<typeof layoutScene> | null = null;
  try {
    scene = layoutScene(valid, frame);
  } catch {
    scene = null;
  }

  if (!scene) {
    return <pre className="cm-ascii rounded-lg bg-muted p-3">{toAscii(valid, frame)}</pre>;
  }

  const caption = valid.frames[frame]?.caption ?? "";

  return (
    <figure className={cn("flex flex-col gap-2.5", className)}>
      <div className="overflow-x-auto rounded-lg border border-border bg-muted/40 p-3">
        <svg
          role="img"
          aria-label={valid.alt_text}
          width={scene.width}
          height={scene.height}
          viewBox={`0 0 ${scene.width} ${scene.height}`}
          className="cm-scene mx-auto block"
          style={{ maxWidth: "100%", height: "auto" }}
        >
          <SceneSvg nodes={scene.nodes} markerId={markerId} />
        </svg>
      </div>

      <figcaption aria-live="polite" className="text-sm leading-relaxed text-muted-foreground">
        {caption}
      </figcaption>

      {frameCount > 1 && (
        <div
          role="group"
          aria-label="Diagram frames"
          className="flex items-center gap-0.5"
        >
          <Button
            variant="ghost"
            size="icon"
            aria-label="Previous frame"
            onClick={() => {
              stop();
              setFrame((prev) => (prev - 1 + frameCount) % frameCount);
            }}
          >
            <AppIcon icon={SkipBackIcon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={playing ? "Pause frames" : "Play frames"}
            aria-pressed={playing}
            onClick={() => setPlaying((prev) => !prev)}
          >
            <AppIcon icon={playing ? PauseIcon : PlayIcon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Next frame"
            onClick={() => {
              stop();
              setFrame((prev) => (prev + 1) % frameCount);
            }}
          >
            <AppIcon icon={SkipForwardIcon} size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label="Reset to first frame"
            onClick={() => {
              stop();
              setFrame(0);
            }}
          >
            <AppIcon icon={RepeatIcon} size={16} />
          </Button>
          <span className="ml-1.5 font-mono text-[11px] tabular-nums text-muted-foreground">
            {frame + 1} / {frameCount}
          </span>
        </div>
      )}
    </figure>
  );
}