import type {
  ComponentHistory,
  ComponentVersion,
  ConfigurationSnapshot,
} from "./component-types";
import { activeAt, decisionAt } from "./component-types";

export interface EvolutionRound {
  round: number;
  firstStep: number;
  lastStep: number;
  resolutionStep?: number;
  start?: ConfigurationSnapshot;
  result?: ConfigurationSnapshot;
}
/** Round boundaries come from recorded events, never from component grades. */
export function evolutionRounds(data: ComponentHistory): EvolutionRound[] {
  const numbers = [
    ...new Set(data.steps.filter((s) => s.round > 0).map((s) => s.round)),
  ];
  return numbers.map((round, i) => {
    const events = data.steps.filter((s) => s.round === round);
    const firstStep = events[0].index,
      lastStep = events.at(-1)!.index;
    const selection = events.findLast((s) => s.kind === "select");
    // A following round also proves where the preceding round handed off.
    const resolutionStep =
      selection?.index ?? (i < numbers.length - 1 ? lastStep : undefined);
    return {
      round,
      firstStep,
      lastStep,
      resolutionStep,
      start: activeAt(data, firstStep - 1),
      result:
        resolutionStep == null ? undefined : activeAt(data, resolutionStep),
    };
  });
}
export function roundChanges(
  data: ComponentHistory,
  round: EvolutionRound,
  step: number,
) {
  const versions = data.versions.filter(
    (v) => v.round === round.round && v.step <= step && v.parent_id,
  );
  const resolved =
    round.resolutionStep != null &&
    round.resolutionStep <= step &&
    !!round.result;
  return data.components.map((c) => {
    const generated = versions.filter((v) => v.component_id === c.id);
    const before = round.start?.components[c.id] || c.baseline_version_id;
    const after = resolved ? round.result?.components[c.id] : undefined;
    const rejected = resolved ? generated.filter((v) => v.id !== after) : [];
    const retained = resolved ? generated.filter((v) => v.id === after) : [];
    // "Rollback" describes the selected state; it does not assert a failed component test.
    const rollback = rejected.length > 0 && after === before;
    return {
      component: c,
      generated,
      before,
      after,
      rejected,
      retained,
      rollback,
      failed: generated.filter(
        (v) => decisionAt(data, v.id, step)?.outcome === "failed",
      ),
    };
  });
}

export interface ExperimentResult {
  versionId: string;
  componentId: string;
  caption: string;
  rejected: boolean;
}
/** Show every recorded experiment outcome, including the unchanged selected versions.
 * A bundle decision alone does not prove that an individual component passed a test.
 */
export function experimentResults(
  data: ComponentHistory,
  round: EvolutionRound,
  step: number,
): ExperimentResult[] {
  return roundChanges(data, round, step).flatMap((change) => {
    const results: ExperimentResult[] = [];
    for (const v of change.generated) {
      const decision = decisionAt(data, v.id, step);
      if (!decision && !change.after) continue;
      const rejected =
        decision?.outcome === "failed" ||
        decision?.outcome === "not_retained" ||
        (!!change.after && change.after !== v.id);
      const caption =
        decision?.scope === "component" && decision.outcome === "failed"
          ? "未通过"
          : decision?.scope === "component" && decision.outcome === "passed"
            ? rejected ? "通过·未采用" : "通过"
            : rejected ? "未采用" : "采用";
      results.push({ versionId: v.id, componentId: v.component_id, caption, rejected });
    }
    if (change.after && !change.generated.some((v) => v.id === change.after))
      results.push({
        versionId: change.after,
        componentId: change.component.id,
        caption: !change.generated.length ? "未优化" : change.after === change.before ? "保留原版" : "回退",
        rejected: false,
      });
    return results;
  });
}

/** X is generation depth, not version number or creation order. Y tracks are local to a round. */
export function componentLayout(data: ComponentHistory, heightBudget?: number, fillHeight = false) {
  const positions = new Map<string, { x: number; y: number }>();
  const rows = new Map<string, { center: number; top: number; height: number }>();
  const testRows = new Map<string, number>();
  const rounds = evolutionRounds(data);
  const byId = new Map(data.versions.map((v) => [v.id, v]));
  const depths = new Map<string, number>();
  const visiting = new Set<string>();
  function depth(v: ComponentVersion): number {
    if (depths.has(v.id)) return depths.get(v.id)!;
    if (visiting.has(v.id)) return 0;
    visiting.add(v.id);
    const parent = v.parent_id ? byId.get(v.parent_id) : undefined;
    const value = parent?.parent_id && parent.round === v.round
      ? depth(parent) + 1
      : 0;
    visiting.delete(v.id);
    depths.set(v.id, value);
    return value;
  }
  for (const v of data.versions) depth(v);
  const roundWidths = rounds.map((r) => 390 + 72 * Math.max(
    0, ...data.versions.filter((v) => v.round === r.round).map((v) => depths.get(v.id)!),
  ));
  const starts = [150];
  for (const span of roundWidths) starts.push(starts.at(-1)! + span);
  const inputX = (index: number) => starts[index] ?? starts.at(-1)!;
  const resultX = (index: number) => inputX(index) + (roundWidths[index] ?? 390);
  const candidateX = (index: number) => inputX(index) + 120;
  const testX = (index: number) => resultX(index) - 140;
  let top = 90;
  for (const c of data.components) {
    const versions = data.versions
      .filter((v) => v.component_id === c.id)
      .sort((a, b) => a.step - b.step || a.id.localeCompare(b.id));
    const local = new Map<string, number>();
    let radius = 12;
    rounds.forEach((r, ri) => {
      const generated = versions.filter((v) => v.round === r.round && v.parent_id);
      const after = r.result?.components[c.id];
      const held = !after || !generated.some((v) => v.id === after);
      generated.forEach((v, i) => {
        // Reserve the centre for an unchanged/rolled-back version when needed.
        const half = Math.floor(generated.length / 2);
        const lane = held ? (i < half ? i - half : i - half + 1) : i - (generated.length - 1) / 2;
        const offset = lane * 28;
        local.set(`${ri}:${v.id}`, offset);
        radius = Math.max(radius, Math.abs(offset) + 12);
      });
    });
    const center = top + radius;
    rows.set(c.id, { center, top, height: radius * 2 });
    for (const v of versions) {
      const ri = rounds.findIndex((r) => r.round === v.round);
      positions.set(v.id, {
        x: v.parent_id && ri >= 0 ? candidateX(ri) + depths.get(v.id)! * 72 : inputX(0),
        y: center + (local.get(`${ri}:${v.id}`) ?? 0),
      });
    }
    for (const [key, offset] of local) testRows.set(key, center + offset);
    top += radius * 2 + 8;
  }
  const naturalHeight = top + 18;
  const height = heightBudget == null ? naturalHeight : fillHeight ? Math.max(160, heightBudget) : Math.min(naturalHeight, Math.max(160, heightBudget));
  if (height !== naturalHeight) {
    const anchor = 90, safeBottom = 18;
    const ratio = (height - anchor - safeBottom) / (naturalHeight - anchor - safeBottom);
    const y = (value: number) => anchor + (value - anchor) * ratio;
    for (const p of positions.values()) p.y = y(p.y);
    for (const [key, value] of testRows) testRows.set(key, y(value));
    for (const row of rows.values()) {
      row.top = y(row.top);
      row.center = y(row.center);
      row.height *= ratio;
    }
  }
  return {
    positions, rows, rounds, depths, height,
    width: Math.max(700, resultX(Math.max(0, rounds.length - 1)) + 58),
    inputX, candidateX, resultX, testX,
    experimentCenterX: (index: number) => (candidateX(index) + testX(index)) / 2,
    boundaryPoint: (index: number, componentId: string) => ({ x: inputX(index), y: rows.get(componentId)!.center }),
    testPoint: (index: number, versionId: string) => ({
      x: testX(index),
      y: testRows.get(`${index}:${versionId}`) ?? rows.get(byId.get(versionId)!.component_id)!.center,
    }),
    phaseBounds: (index: number) => ({
      input: { x: inputX(index) - 24, width: 89 },
      experiment: { x: inputX(index) + 65, width: (roundWidths[index] ?? 390) - 115 },
      test: { x: testX(index) - 50, width: 140 },
    }),
    roundBounds: (index: number) => ({
      x: inputX(index) - 24, y: 4,
      width: (roundWidths[index] ?? 390) + 64, height: height - 8,
    }),
  };
}

/** Connect to an occurrence of the actual parent ID, never to the preceding V-number. */
export function versionParentAnchor(
  data: ComponentHistory,
  layout: ReturnType<typeof componentLayout>,
  version: ComponentVersion,
) {
  if (!version.parent_id) return undefined;
  const parent = data.versions.find((v) => v.id === version.parent_id);
  const point = parent && layout.positions.get(parent.id);
  if (!parent || !point) return undefined;
  const index = layout.rounds.findIndex((r) => r.round === version.round);
  const round = layout.rounds[index];
  const baseline = data.components.find(
    (c) => c.id === version.component_id,
  )?.baseline_version_id;
  if (
    round &&
    parent.id === (round.start?.components[version.component_id] || baseline)
  )
    return {
      versionId: parent.id,
      x: layout.inputX(index),
      y: layout.rows.get(version.component_id)!.center,
      kind: "input" as const,
    };
  for (let i = index - 1; i >= 0; i--) {
    const prior = layout.rounds[i];
    if (
      prior.result?.components[version.component_id] === parent.id &&
      prior.resolutionStep != null &&
      prior.resolutionStep < version.step
    )
      return {
        versionId: parent.id,
        x: layout.resultX(i),
        y: layout.rows.get(version.component_id)!.center,
        kind: "result" as const,
      };
  }
  return { versionId: parent.id, ...point, kind: "origin" as const };
}
