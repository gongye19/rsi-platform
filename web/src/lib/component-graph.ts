import type { Edge, Node } from "@xyflow/react";
import {
  componentLayout,
  experimentResults,
  roundChanges,
  versionParentAnchor,
} from "./component-layout";
import { COMPONENT_COLORS, decisionAt, type ComponentHistory } from "./component-types";

export type PointData = {
  versionId: string;
  componentId: string;
  componentName: string;
  label: string;
  caption: string;
  color: string;
  round: number;
  stage: "input" | "experiment" | "test";
  rejected: boolean;
  root: boolean;
  contextName: boolean;
  arrival: boolean;
  delay: number;
};
export type BranchData = {
  color: string;
  kind: "parent" | "assessment" | "held" | "retained";
  parentId?: string;
  versionId: string;
  round: number;
  arrival: boolean;
  delay: number;
  rejected: boolean;
};
export type LineagePoint = Node<PointData, "version">;
export type LineageBranch = Edge<BranchData, "branch">;

/** Project recorded occurrences onto React Flow. Node identity is not a V-number.
 * Boundaries are shared by adjacent rounds; assessment references keep their IDs.
 */
export function componentGraph(data: ComponentHistory, step: number, height?: number, fillHeight = false, uniformLanes = false) {
  const layout = componentLayout(data, height, fillHeight, uniformLanes);
  const nodes: LineagePoint[] = [];
  const edges: LineageBranch[] = [];
  const byId = new Map(data.versions.map((v) => [v.id, v]));
  const boundary = (componentId: string, index: number) => `${componentId}:boundary:${index}`;
  const generated = (id: string) => `${id}:generated`;
  const assessed = (id: string, round: number) => `${id}:tested:${round}`;

  data.components.forEach((component, ci) => {
    const color = COMPONENT_COLORS[ci % COMPONENT_COLORS.length];
    const point = (
      id: string, versionId: string, x: number, y: number,
      round: number, stage: PointData["stage"], caption = "",
      rejected = false, arrival = false, delay = 0.7, root = false,
    ) => {
      if (!byId.has(versionId)) return;
      nodes.push({
        id, type: "version", position: { x, y }, width: 14, height: 14,
        draggable: false, selectable: false, focusable: false,
        data: {
          versionId, componentId: component.id, componentName: component.name,
          label: byId.get(versionId)!.label, color, round, stage, caption,
          rejected, root, arrival, delay,
          contextName: stage === "input" && !root && round !== layout.rounds.at(-1)?.round,
        },
      });
    };
    const branch = (
      id: string, source: string, target: string, kind: BranchData["kind"],
      versionId: string, round: number, arrival: boolean, delay = 0,
      rejected = false, parentId?: string,
    ) => edges.push({
      id, source, target, type: "branch", selectable: false, focusable: false,
      data: { color, kind, versionId, round, arrival, delay, rejected, parentId },
    });

    const base = layout.positions.get(component.baseline_version_id)!;
    point(boundary(component.id, 0), component.baseline_version_id, base.x, base.y,
      0, "input", "", false, false, 0, true);

    layout.rounds.forEach((round, ri) => {
      if (round.firstStep > step) return;
      const change = roundChanges(data, round, step).find((c) => c.component.id === component.id)!;
      const outcomes = experimentResults(data, round, step).filter((o) => o.componentId === component.id);
      const result = boundary(component.id, ri + 1);
      const resolvedNow = round.resolutionStep === step;
      if (change.after) {
        point(result, change.after, layout.resultX(ri),
          layout.rounds[ri + 1] ? layout.rows.get(component.id)!.center : layout.testPoint(ri, change.after).y,
          round.round, "input", "", false, resolvedNow, 0.9);
      }

      // Resolve an occurrence of the actual parent, including revived rejected branches.
      const parentOccurrence = (versionId: string) => {
        const version = byId.get(versionId)!;
        const anchor = versionParentAnchor(data, layout, version)!;
        if (anchor.kind === "input") return boundary(component.id, ri);
        if (anchor.kind === "result") {
          const prior = layout.rounds.findIndex((r, i) => i < ri && layout.resultX(i) === anchor.x);
          if (prior >= 0) return boundary(component.id, prior + 1);
        }
        const parent = byId.get(version.parent_id!)!;
        if (!parent.parent_id) return boundary(component.id, 0);
        // A previous rejected result can be a real source, but never extends by default.
        for (let j = ri - 1; j >= 0; j--) {
          const candidate = assessed(parent.id, layout.rounds[j].round);
          if (nodes.some((n) => n.id === candidate)) return candidate;
        }
        return generated(parent.id);
      };

      for (const version of change.generated) {
        const position = layout.positions.get(version.id)!;
        const depth = layout.depths.get(version.id) || 0;
        const arrival = version.step === step;
        // Sibling nodes share x; animation order never changes genealogy or layout.
        const delay = Math.min(0.5, depth * 0.2);
        point(generated(version.id), version.id, position.x, position.y,
          round.round, "experiment", "", false, arrival, delay + 0.55);
        branch(`parent:${version.id}`, parentOccurrence(version.id), generated(version.id),
          "parent", version.id, round.round, arrival, delay, false, version.parent_id!);
      }

      for (const outcome of outcomes) {
        const isNew = decisionAt(data, outcome.versionId, step)?.step === step || resolvedNow;
        const tested = layout.testPoint(ri, outcome.versionId);
        const testId = assessed(outcome.versionId, round.round);
        point(testId, outcome.versionId, tested.x, tested.y, round.round, "test",
          outcome.caption, outcome.rejected, isNew, 0.62);
        const isGenerated = change.generated.some((v) => v.id === outcome.versionId);
        let source = isGenerated ? generated(outcome.versionId) : boundary(component.id, ri);
        if (!isGenerated && outcome.versionId !== change.before) {
          source = byId.get(outcome.versionId)?.parent_id
            ? generated(outcome.versionId) : boundary(component.id, 0);
          for (let j = ri - 1; j >= 0; j--) {
            if (layout.rounds[j].result?.components[component.id] === outcome.versionId) {
              source = boundary(component.id, j + 1);
              break;
            }
          }
        }
        branch(`test:${round.round}:${outcome.versionId}`, source, testId,
          isGenerated ? "assessment" : "held", outcome.versionId,
          round.round, isNew, 0, outcome.rejected);
        if (change.after === outcome.versionId) {
          branch(`handoff:${round.round}:${component.id}`, testId, result, "retained",
            outcome.versionId, round.round, resolvedNow, 0.58);
        }
      }
    });
  });
  const ids = new Set(nodes.map((n) => n.id));
  return { layout, nodes, edges: edges.filter((e) => ids.has(e.source) && ids.has(e.target)) };
}
