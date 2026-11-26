"use client";
import { memo, useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { combinedRoundResults, type ResultMetric } from "@/lib/round-results";
import { measurementDomain } from "@/lib/presentation";
import type { ComponentHistory } from "@/lib/component-types";

const series = [
  { key: "score", label: "Score", unit: "", color: "#5e6ad2" },
  { key: "seconds", label: "Time", unit: " s", color: "#488c82" },
  { key: "tokens", label: "Tokens", unit: " tokens", color: "#ad8552" },
] as const;
const config = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]));
const roundName = (round: number) => round === 0 ? "Baseline" : `Round ${round}`;
const format = (n: number, metric: ResultMetric) =>
  `${Intl.NumberFormat("en-US", { maximumFractionDigits: 2, notation: metric === "tokens" && n >= 10000 ? "compact" : "standard" }).format(n)}${series.find((s) => s.key === metric)?.unit || ""}`;
const tick = (n: number, precision = 1) => Intl.NumberFormat("en-US", {
  notation: Math.abs(n) >= 10000 ? "compact" : "standard", maximumFractionDigits: precision,
}).format(n);
type MeasurementPoint = ReturnType<typeof combinedRoundResults>[number];

function RoundOutcomeChart({ data, step, activeRound, onHoverRound, onRound }: {
  data: ComponentHistory;
  step: number;
  activeRound: number;
  onHoverRound: (round: number | null) => void;
  onRound: (round: number) => void;
}) {
  const points = useMemo(() => combinedRoundResults(data, step), [data, step]);
  const current = points.find((p) => p.round === activeRound);
  const available = Object.fromEntries(series.map((s) => [s.key, points.some((p) => p[s.key] != null)]));
  const domains = useMemo(() => Object.fromEntries(series.map((s) => [s.key, measurementDomain(points.map((p) => p[s.key]))])), [points]);
  return <div className="ce-chart-scroll" aria-label="Score, time and tokens by round, horizontally scrollable">
    <div className="ce-round-chart" style={{ minWidth: Math.max(360, points.length * 80 + 100) }}>
      <div className="ce-series-legend" aria-label="Recorded metrics for the selected round">
        {series.map((s) => <span key={s.key} data-series={s.key} title={!available[s.key] ? "No measurement recorded for this metric" : current?.reused ? "Previously measured" : undefined} className={available[s.key] ? "" : "is-unmeasured"} style={{ color: available[s.key] ? s.color : undefined }}>
          <i style={{ background: s.color }} />{s.label}
          <strong>{current?.[s.key] != null ? format(current[s.key]!, s.key) : "—"}</strong>
        </span>)}
      </div>
      <ChartContainer config={config} className="ce-recharts" initialDimension={{ width: 500, height: 400 }}>
        <LineChart accessibilityLayer data={points} margin={{ top: 30, right: 8, bottom: 12, left: 0 }}
          onMouseMove={(_state, event) => {
            // Recharts' tooltip index can lag the pointer by one event. Read our
            // rendered point centres so the linked round always matches the hit.
            const direct = (event.target as Element).closest("[data-score-round]");
            if (direct) { onHoverRound(Number(direct.getAttribute("data-score-round"))); return; }
            const dots = Array.from(event.currentTarget.querySelectorAll<SVGGElement>("[data-score-round]"));
            let round: number | null = null, distance = Infinity;
            for (const dot of dots) {
              const bounds = dot.querySelector(".ce-point-dot")?.getBoundingClientRect();
              if (!bounds) continue;
              const next = Math.abs(event.clientX - bounds.x - bounds.width / 2);
              if (next < distance) { distance = next; round = Number(dot.getAttribute("data-score-round")); }
            }
            onHoverRound(round);
          }}
          onMouseLeave={() => onHoverRound(null)}>
          <CartesianGrid vertical={false} stroke="#e6e9ef" strokeDasharray="3 5" />
          <XAxis dataKey="round" type="category" allowDuplicatedCategory={false} tickLine={false}
            axisLine={{ stroke: "#d4d4d8" }} tickMargin={12} height={38}
            tickFormatter={(r) => roundName(Number(r))} padding={{ left: 22, right: 22 }} />
          {series.map((s, i) => <YAxis key={s.key} className={`ce-axis-${s.key}`} yAxisId={s.key}
            orientation={i === 0 ? "left" : "right"} width={i === 0 ? 42 : 50}
            tickLine={false} axisLine={false} tickMargin={6} tickCount={5}
            domain={domains[s.key] as [number, number]} allowDataOverflow
            ticks={Array.from({ length: 5 }, (_, i) => domains[s.key][0] + (domains[s.key][1] - domains[s.key][0]) * i / 4)}
            tick={{ fill: s.color, style: { fill: s.color }, fontSize: 14 }} tickFormatter={n => tick(n, s.key === "score" ? 2 : 1)} hide={!available[s.key]} />)}
          <ChartTooltip cursor={false} isAnimationActive={false} content={<ChartTooltipContent
            labelFormatter={(_v, payload) => `${roundName(payload[0]?.payload?.round ?? 0)} · Retained configuration`}
            formatter={(v, _name, item) => {
              const key = item.dataKey as ResultMetric;
              const s = series.find((s) => s.key === key)!;
              return <div className="ce-score-tooltip"><span className={available[s.key] ? "" : "is-unmeasured"} style={{ color: available[s.key] ? s.color : undefined }}>{s.label}</span><strong>{format(Number(v), key)}</strong></div>;
            }} />} />
          {current && <ReferenceLine x={current.round} yAxisId="score" stroke="#5e6ad2" strokeOpacity={0.6} strokeWidth={1.5} strokeDasharray="4 5" />}
          {series.map((s) => <Line key={s.key} yAxisId={s.key} dataKey={s.key} type="bumpX"
            stroke={s.color} strokeWidth={1.8} strokeDasharray={s.key === "tokens" ? "6 4" : undefined}
            connectNulls={false} activeDot={false} isAnimationActive={false} animationDuration={650} animationEasing="ease-in-out"
            dot={({ cx, cy, payload }: { cx?: number; cy?: number; payload?: MeasurementPoint }) => {
              if (cx == null || cy == null || !payload || payload[s.key] == null) return <g key={`${s.key}-empty`} />;
              const linked = payload.round === activeRound;
              return <g key={`${s.key}-${payload.round}`} className="ce-measurement-point" role="button" tabIndex={0}
                data-score-round={payload.round} data-active={linked} data-metric={s.key}
                aria-label={`${roundName(payload.round)}, ${s.label} ${format(payload[s.key]!, s.key)}, inspect lineage`}
                onMouseEnter={() => onHoverRound(payload.round)} onMouseLeave={() => onHoverRound(null)}
                onFocus={() => onHoverRound(payload.round)} onBlur={() => onHoverRound(null)}
                onClick={(event) => { event.stopPropagation(); onRound(payload.round); }}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onRound(payload.round); } }}>
                <title>{roundName(payload.round)} · {s.label} {format(payload[s.key]!, s.key)}</title>
                <circle cx={cx} cy={cy} r={17} fill="transparent" />
                <circle cx={cx} cy={cy} r={linked ? 10 : 8} fill={s.color} fillOpacity={linked ? 0.14 : 0} className="ce-point-halo" />
                <circle cx={cx} cy={cy} r={linked ? 5 : 4} fill={s.color} stroke="white" strokeWidth={1.5} className="ce-point-dot" />
              </g>;
            }} />)}
        </LineChart>
      </ChartContainer>
      <nav className="ce-round-navigation" aria-label="Inspect evolution rounds" data-chart-linked-round={activeRound}>
        {points.map((point) => <button key={point.round} aria-label={`Inspect ${roundName(point.round)} lineage`}
          aria-pressed={point.round === activeRound}
          onMouseEnter={() => onHoverRound(point.round)} onMouseLeave={() => onHoverRound(null)}
          onFocus={() => onHoverRound(point.round)} onBlur={() => onHoverRound(null)} onClick={() => onRound(point.round)}>
          <i />{roundName(point.round)}
        </button>)}
      </nav>
    </div>
  </div>;
}
export default memo(RoundOutcomeChart);
