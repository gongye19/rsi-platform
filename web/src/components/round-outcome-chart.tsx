"use client";
import { memo, useMemo } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, XAxis, YAxis } from "recharts";
import { ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { combinedRoundResults, type ResultMetric } from "@/lib/round-results";
import { measurementDomain } from "@/lib/presentation";
import type { ComponentHistory } from "@/lib/component-types";

const series = [
  { key: "score", label: "评分", unit: "", color: "#2a78d6" },
  { key: "seconds", label: "耗时", unit: " s", color: "#d55181" },
  { key: "tokens", label: "Token", unit: " tokens", color: "#7d3c98" },
] as const;
const config = Object.fromEntries(series.map((s) => [s.key, { label: s.label, color: s.color }]));
const roundName = (round: number) => round === 0 ? "初始" : `第 ${round} 轮`;
const format = (n: number, metric: ResultMetric) =>
  `${Intl.NumberFormat("en-US", { maximumFractionDigits: 2, notation: metric === "tokens" && n >= 10000 ? "compact" : "standard" }).format(n)}${series.find((s) => s.key === metric)?.unit || ""}`;
const tick = (n: number) => Intl.NumberFormat("en-US", {
  notation: Math.abs(n) >= 10000 ? "compact" : "standard", maximumFractionDigits: 1,
}).format(n);
type MeasurementPoint = ReturnType<typeof combinedRoundResults>[number];

function RoundOutcomeChart({ data, step, activeRound, onHoverRound, onRound, playing }: {
  data: ComponentHistory;
  step: number;
  activeRound: number;
  onHoverRound: (round: number | null) => void;
  onRound: (round: number) => void;
  playing: boolean;
}) {
  const points = useMemo(() => combinedRoundResults(data, step), [data, step]);
  const current = points.find((p) => p.round === activeRound);
  const available = Object.fromEntries(series.map((s) => [s.key, points.some((p) => p[s.key] != null)]));
  const domains = useMemo(() => Object.fromEntries(series.map((s) => [s.key, measurementDomain(points.map((p) => p[s.key]))])), [points]);
  return <div className="ce-chart-scroll" aria-label="评分、耗时和Token同图展示，可横向滚动">
    <div className="ce-round-chart" style={{ minWidth: Math.max(360, points.length * 80 + 100) }}>
      <div className="ce-series-legend" aria-label="三个指标及当前轮数值">
        {series.map((s) => <span key={s.key} data-series={s.key} title={current?.reused ? "沿用此前测量" : undefined} style={{ color: s.color }}>
          <i style={{ background: s.color }} />{s.label}
          <strong>{current?.[s.key] != null ? format(current[s.key]!, s.key) : "待评测"}</strong>
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
            tick={{ fill: s.color, style: { fill: s.color }, fontSize: 11 }} tickFormatter={tick} hide={!available[s.key]} />)}
          <ChartTooltip cursor={false} isAnimationActive={false} content={<ChartTooltipContent
            labelFormatter={(_v, payload) => `${roundName(payload[0]?.payload?.round ?? 0)} · 保留配置`}
            formatter={(v, _name, item) => {
              const key = item.dataKey as ResultMetric;
              const s = series.find((s) => s.key === key)!;
              return <div className="ce-score-tooltip"><span style={{ color: s.color }}>{s.label}</span><strong>{format(Number(v), key)}</strong></div>;
            }} />} />
          {current && <ReferenceLine x={current.round} yAxisId="score" stroke="#2a78d6" strokeOpacity={0.6} strokeWidth={1.5} strokeDasharray="4 5" />}
          {series.map((s) => <Line key={s.key} yAxisId={s.key} dataKey={s.key} type="bumpX"
            stroke={s.color} strokeWidth={2.8} strokeDasharray={s.key === "tokens" ? "6 4" : undefined}
            connectNulls={false} activeDot={false} isAnimationActive={playing} animationDuration={650} animationEasing="ease-in-out"
            dot={({ cx, cy, payload }: { cx?: number; cy?: number; payload?: MeasurementPoint }) => {
              if (cx == null || cy == null || !payload || payload[s.key] == null) return <g key={`${s.key}-empty`} />;
              const linked = payload.round === activeRound;
              return <g key={`${s.key}-${payload.round}`} className="ce-measurement-point" role="button" tabIndex={0}
                data-score-round={payload.round} data-active={linked} data-metric={s.key}
                aria-label={`${roundName(payload.round)}，${s.label} ${format(payload[s.key]!, s.key)}，点击定位组件谱系`}
                onMouseEnter={() => onHoverRound(payload.round)} onMouseLeave={() => onHoverRound(null)}
                onFocus={() => onHoverRound(payload.round)} onBlur={() => onHoverRound(null)}
                onClick={(event) => { event.stopPropagation(); onRound(payload.round); }}
                onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onRound(payload.round); } }}>
                <title>{roundName(payload.round)} · {s.label} {format(payload[s.key]!, s.key)}</title>
                <circle cx={cx} cy={cy} r={17} fill="transparent" />
                <circle cx={cx} cy={cy} r={linked ? 13 : 9} fill={s.color} fillOpacity={linked ? 0.14 : 0} className="ce-point-halo" />
                <circle cx={cx} cy={cy} r={linked ? 7.5 : 5.5} fill={s.color} stroke="white" strokeWidth={2.2} className="ce-point-dot" />
              </g>;
            }} />)}
        </LineChart>
      </ChartContainer>
      <nav className="ce-round-navigation" aria-label="定位进化轮次" data-chart-linked-round={activeRound}>
        {points.map((point) => <button key={point.round} aria-label={`定位${roundName(point.round)}组件谱系`}
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
