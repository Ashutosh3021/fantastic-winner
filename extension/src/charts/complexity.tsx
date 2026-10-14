import { useId, useMemo } from "react";

import type { ComplexityChart } from "../schemas";
import { CURVE_ORDER, curveFor, verdictFor } from "./scale";
import { Badge } from "../ui/components/badge";
import { AppIcon, InformationCircleIcon } from "../ui/icons";

/**
 * Complexity graph (§13.1).
 *
 * The server sends **classes and numbers only**; every curve here is computed
 * on the client from those classes. The AI is never asked for chart points, so
 * there is nothing to hallucinate. The caption says plainly that this is a
 * model of growth, not a benchmark.
 */

const W = 320;
const H = 190;
const PAD = { top: 12, right: 10, bottom: 26, left: 34 };
const SAMPLES = 40;

type Props = {
  chart: ComplexityChart;
  timeClass: string;
};

export function ComplexityGraph({ chart, timeClass }: Props) {
  const clipId = useId();
  const plotW = W - PAD.left - PAD.right;
  const plotH = H - PAD.top - PAD.bottom;

  const yMax = Math.log10(chart.budget_ops) + 1;

  const { paths, samples, clipped } = useMemo(() => {
    const points = Array.from({ length: SAMPLES }, (_, i) => {
      // Geometric sampling so small n stays visible next to a huge N_max.
      const t = i / (SAMPLES - 1);
      return 1 * (chart.n_max ** t);
    });

    const toX = (n: number) => PAD.left + ((Math.log(n) - 0) / Math.log(chart.n_max)) * plotW;
    const toY = (ops: number) => {
      const v = Math.log10(Math.max(1, ops));
      return PAD.top + plotH - Math.min(1, v / yMax) * plotH;
    };

    const build = (fn: (n: number) => number) =>
      points
        .map((n, i) => {
          const y = toY(fn(n));
          const clippedHere = y <= PAD.top + 0.5;
          return `${i === 0 ? "M" : "L"}${toX(n).toFixed(1)},${clippedHere ? PAD.top : y.toFixed(1)}`;
        })
        .join(" ");

    const marks = points.map((n) => ({
      n,
      x: toX(n),
      y: toY(curveFor(timeClass)(n)),
    }));

    return {
      samples: marks,
      paths: CURVE_ORDER.map((label) => ({ label, d: build(curveFor(label)) })),
      clipped: points.some((n) => Math.log10(curveFor(timeClass)(n)) > yMax),
    };
  }, [chart.budget_ops, chart.n_max, timeClass, plotW, plotH, yMax]);

  const marker = samples[samples.length - 1];
  const verdict = verdictFor(timeClass, chart.n_max, chart.budget_ops);
  const isBrute = chart.brute_force_class && chart.brute_force_class !== timeClass;

  return (
    <figure className="flex flex-col gap-2">
      <svg
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label={`Growth curves for ${timeClass} up to an input of ${chart.n_max}. ${verdict.label}.`}
        className="cm-scene w-full"
      >
        <clipPath id={clipId}>
          <rect x={PAD.left} y={PAD.top} width={plotW} height={plotH} />
        </clipPath>

        {/* Budget line: "about what fits in a second", a rule of thumb. */}
        <line
          x1={PAD.left}
          y1={PAD.top + plotH - (yMax - 1) / yMax * plotH}
          x2={PAD.left + plotW}
          y2={PAD.top + plotH - (yMax - 1) / yMax * plotH}
          stroke="var(--cm-line-strong)"
          strokeDasharray="4 3"
        />
        <text
          x={PAD.left + 4}
          y={PAD.top + plotH - (yMax - 1) / yMax * plotH - 4}
          fontSize={9}
          fill="var(--cm-text-muted)"
        >
          ≈ 1 second (rule of thumb)
        </text>

        {paths.map(({ label, d }) => (
          <path
            key={label}
            d={d}
            fill="none"
            stroke="var(--cm-line)"
            strokeWidth={1}
            clipPath={`url(#${clipId})`}
          />
        ))}

        <path
          d={paths.find((p) => p.label === (timeClass as never))?.d ?? ""}
          fill="none"
          stroke="var(--cm-brand)"
          strokeWidth={2.2}
          clipPath={`url(#${clipId})`}
        />

        {isBrute && (
          <path
            d={paths.find((p) => p.label === chart.brute_force_class)?.d ?? ""}
            fill="none"
            stroke="var(--cm-line-strong)"
            strokeWidth={1.4}
            strokeDasharray="5 3"
            clipPath={`url(#${clipId})`}
          />
        )}

        {marker && (
          <circle cx={marker.x} cy={marker.y} r={3.5} fill="var(--cm-brand)" />
        )}

        <line
          x1={PAD.left}
          y1={PAD.top + plotH}
          x2={PAD.left + plotW}
          y2={PAD.top + plotH}
          stroke="var(--cm-line-strong)"
        />
        <text x={PAD.left} y={H - 6} fontSize={9} fill="var(--cm-text-muted)">
          1
        </text>
        <text
          x={PAD.left + plotW}
          y={H - 6}
          fontSize={9}
          textAnchor="end"
          fill="var(--cm-text-muted)"
        >
          {compact(chart.n_max)}
        </text>
        <text
          x={6}
          y={PAD.top + 4}
          fontSize={9}
          fill="var(--cm-text-muted)"
          transform={`rotate(-90 6 ${PAD.top + 4})`}
        >
          operations
        </text>
      </svg>

      <figcaption className="flex flex-wrap items-center gap-2 text-[11px] leading-relaxed text-muted-foreground">
        <Badge
          variant={
            verdict.tone === "good" ? "success" : verdict.tone === "warn" ? "warning" : "danger"
          }
        >
          {verdict.label}
        </Badge>
        <span className="min-w-0">
          Max input <span className="font-mono tabular-nums">{compact(chart.n_max)}</span>
          {chart.n_max_source === "assumed" && " (assumed — no constraints parsed)"}
          {clipped && " · your curve is above the chart"}
        </span>
        {chart.estimated && (
          <span className="inline-flex items-center gap-1">
            <AppIcon icon={InformationCircleIcon} size={12} />
            estimated
          </span>
        )}
      </figcaption>

      <details className="group text-[11px]">
        <summary className="cursor-pointer list-none text-muted-foreground transition-colors hover:text-foreground">
          <span className="group-open:hidden">Show as numbers</span>
          <span className="hidden group-open:inline">Hide the numbers</span>
        </summary>
        <table className="mt-2 w-full text-left">
          <caption className="sr-only">Operations at the maximum input size</caption>
          <thead>
            <tr className="text-muted-foreground">
              <th scope="col" className="pb-1 font-normal">
                Class
              </th>
              <th scope="col" className="pb-1 text-right font-normal">
                Operations at N
              </th>
            </tr>
          </thead>
          <tbody>
            {CURVE_ORDER.map((label) => (
              <tr
                key={label}
                className={label === timeClass ? "font-semibold text-foreground" : "text-muted-foreground"}
              >
                <td className="py-0.5">{label}</td>
                <td className="py-0.5 text-right font-mono tabular-nums">
                  {formatOps(curveFor(label)(chart.n_max))}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </figure>
  );
}

function compact(n: number): string {
  if (n >= 1_000_000) return `${Math.round(n / 100_000) / 10}M`;
  if (n >= 1_000) return `${Math.round(n / 100) / 10}k`;
  return String(Math.round(n));
}

function formatOps(ops: number): string {
  if (!Number.isFinite(ops) || ops > 1e30) return "far beyond the chart";
  if (ops >= 1e9) return `${(ops / 1e9).toFixed(1)}B`;
  if (ops >= 1e6) return `${(ops / 1e6).toFixed(1)}M`;
  if (ops >= 1e3) return `${(ops / 1e3).toFixed(1)}k`;
  return String(Math.round(ops));
}