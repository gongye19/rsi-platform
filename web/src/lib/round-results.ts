import { evolutionRounds } from "./component-layout";
import type {
  ComponentHistory,
  ConfigurationSnapshot,
} from "./component-types";
export type ResultMetric = "score" | "seconds" | "tokens";
export interface RoundResult {
  round: number;
  label: string;
  value: number | null;
  bundle?: ConfigurationSnapshot;
  reused: boolean;
}
/** Only recorded final handoffs; no candidate scores, future decisions, or synthetic zeroes. */
export function roundResults(
  data: ComponentHistory,
  step: number,
  metric: ResultMetric,
): RoundResult[] {
  const value = (bundle?: ConfigurationSnapshot) => {
    const v =
      metric === "score" ? bundle?.metrics.score : bundle?.execution[metric];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  };
  const baseline = data.bundles.find(
    (b) => b.id === data.steps[0]?.active_bundle_id,
  );
  const points: RoundResult[] = [
    {
      round: 0,
      label: "初始",
      value: value(baseline),
      bundle: baseline,
      reused: false,
    },
  ];
  for (const r of evolutionRounds(data)) {
    if (r.resolutionStep == null || r.resolutionStep > step || !r.result)
      continue;
    points.push({
      round: r.round,
      label: `第 ${r.round} 轮`,
      value: value(r.result),
      bundle: r.result,
      reused: r.result.round !== r.round,
    });
  }
  return points;
}

/** Align all three measurements on the same adopted snapshot and round. */
export function combinedRoundResults(data: ComponentHistory, step: number) {
  const scores = roundResults(data, step, "score");
  const seconds = roundResults(data, step, "seconds");
  const tokens = roundResults(data, step, "tokens");
  return scores.map(({ value, ...point }, i) => ({
    ...point,
    score: value,
    seconds: seconds[i].value,
    tokens: tokens[i].value,
  }));
}
