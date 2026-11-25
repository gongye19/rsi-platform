export type Metrics = {pass_at_1?: number; trial_success_count?: number; trial_count?: number; task_count?: number};
export type Policy = {allowed: string[]; denied: string[]; experimental_fields: string[]};
export type Connection = {model?: string; managed_by?: string; api?: string};
export type Settings = {models: {execution: string; analysis: string}; components: Policy; parameters: Record<string, number>; initial_harness: string; full_evaluation: boolean};
export type Configuration = {benchmark?: string; models?: {execution?: Connection; analysis?: Connection}; components?: Policy; parameters?: Record<string, number>; initial_harness?: string; full_evaluation?: boolean};
export type TestResult = {metrics: Metrics; repeats?: number; reused_initial?: boolean};
export type Run = {id: string; state: string; error: string; attempt: number; read_only: number; created: number; updated: number; stage?: string; phase?: {id: string; label: string; checkpoint?: string; initial_ready: boolean}; selected_version?: string; baseline_metrics: Metrics; tests: {initial?: TestResult; selected?: TestResult}; budget: {used?: number; total?: number; remaining?: number}; configuration: Configuration; iteration_history: {iteration: number; candidate_version: string; review_decision: string; review_rationale: string; rollout_metrics?: Metrics; evaluation_mode?: string}[]};
export type Artifact = {root: number; path: string; bytes: number};
export type Event = {seq: number; kind: string; at: number; payload: unknown};
export type Parameter = {key: string; label: string; default: number; min: number; max: number};
export type Options = {models: {id: string; label: string; model: string; configured: boolean}[]; components: {id: string; name: string}[]; proposal_only: string[]; experimental_fields: string[]; parameters: Parameter[]};
export type Preview = Configuration & {model_selection: Settings['models']; components: Policy; parameters: Record<string, number>; readiness: string; business_agent: boolean; mode: string};
export const stateLabels: Record<string, string> = {draft: 'Draft', queued: 'Queued', running: 'Running', stopping: 'Stopping', stopped: 'Stopped', failed: 'Failed', interrupted: 'Interrupted', succeeded: 'Completed'};
export const componentLabels: Record<string, string> = {
  instructions_rules: 'Standing rules', system_prompt: 'System prompt', skills: 'Skills', agent_definitions: 'Agent definitions',
  execution_policy: 'Execution & scheduling', tool_description: 'Tool descriptions', tool_parameter_description: 'Tool parameters',
  tool_availability: 'Tool availability', permissions: 'Permissions', commands: 'Commands', reference_sources: 'Reference sources',
  context_management: 'Context management', custom_tools: 'Custom tools', plugin_tool_system: 'Plugin logic', mcp_servers: 'MCP integration', experimental_policies: 'Experimental policies',
  model_provider: 'Model / provider', runtime_env: 'Runtime environment', file_attachments: 'File attachments', tool_return: 'Tool outputs', diagnostic: 'Diagnostics',
};
export function metric(m?: Metrics) {return m?.pass_at_1 == null ? '—' : `${(m.pass_at_1 * 100).toFixed(1)}%`;}
export function counts(m?: Metrics) {return m?.trial_count == null ? 'No measurements' : `${m.trial_success_count ?? '?'} / ${m.trial_count} trials`;}
export class PlatformError extends Error {constructor(message: string, public status: number) {super(message);this.name='PlatformError';}}
export async function platformRead<T>(query = '', init?: RequestInit): Promise<T> {
  const response = await fetch('/api/platform' + query, {cache: 'no-store', ...init});
  const data = await response.json();
  if (!response.ok) throw new PlatformError(data.error || 'The request failed. Please try again.',response.status);
  return data;
}
