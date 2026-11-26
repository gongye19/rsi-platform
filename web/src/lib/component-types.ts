/** No optimization-method roles appear in this contract. */
export interface HarnessComponent {
  id: string;
  name: string;
  description: string;
  baseline_version_id: string;
}
export interface ComponentVersion {
  id: string;
  component_id: string;
  label: string;
  parent_id: string | null;
  step: number;
  round: number;
  digest: string;
  present: boolean;
  files: { path: string; change: string; diff: string }[];
  notes: string;
  source?: { task_id: string; candidate_id: string };
}
export interface ConfigurationSnapshot {
  id: string;
  label: string;
  step: number;
  round: number;
  components: Record<string, string>;
  execution: {
    status: string;
    seconds?: number | null;
    tokens?: number | null;
  };
  metrics: Record<string, number | null>;
}
export interface EvolutionStep {
  index: number;
  round: number;
  label: string;
  kind: string;
  bundle_id?: string;
  active_bundle_id?: string;
}
export interface VersionDecision {
  version_id: string;
  step: number;
  scope: "component" | "bundle";
  outcome: "passed" | "failed" | "retained" | "not_retained";
  reason: string;
  evidence?: string;
}
export interface ComponentHistory {
  schema_version: "1.0";
  id: string;
  title: string;
  algorithm: string;
  source: "historical" | "example";
  notice: string;
  profile?: { id: string; runtime: string; version: string };
  context: { initial_ready?: boolean; task_id?: string; domain?: string; question?: string };
  tasks?: { id: string; domain: string }[];
  components: HarnessComponent[];
  versions: ComponentVersion[];
  bundles: ConfigurationSnapshot[];
  steps: EvolutionStep[];
  decisions: VersionDecision[];
}
/** Each component keeps one color across names, versions and ancestry. */
export const COMPONENT_COLORS = [
  "#4f75bd", "#8766ae", "#378186", "#996b33",
  "#7167bb", "#ab5e7d", "#358069", "#5b779b",
  "#8c6890", "#5f7592", "#a35e78", "#4f7e85",
  "#8369a1", "#a06862", "#527799", "#797084",
];
export const decisionLabels = {
  passed: "Component check passed",
  failed: "Component check failed",
  retained: "Retained with Harness",
  not_retained: "Not retained with Harness",
};
export function decisionAt(data: ComponentHistory, id: string, step: number) {
  return data.decisions
    .filter((d) => d.version_id === id && d.step <= step)
    .at(-1);
}
export function activeAt(data: ComponentHistory, step: number) {
  const bid = data.steps
    .slice(0, step + 1)
    .reverse()
    .find((s) => s.active_bundle_id)?.active_bundle_id;
  return data.bundles.find((b) => b.id === bid);
}
