export interface TaskSummary {
  id: string;
  index: number;
  domain: string;
  question: string;
  status: string;
  selected?: string;
  has_experience: boolean;
  rollouts: number;
  solver_tokens: number;
  solver_seconds: number;
}
export interface ActorUsage {
  requests: number;
  tokens_observed: number;
  missing_usage: number;
  failed: number;
  latest_at?: string;
  first_at?: string;
  current: { task_id?: string; role?: string; label?: string };
}
export interface MatrixRow {
  candidate: string;
  task_id: string;
  execution_ok: boolean;
  grader_ok: boolean;
  passed: boolean | null;
  metrics?: { rs?: number };
}
export interface Overview {
  id: string;
  name: string;
  checked_at: string;
  status: string;
  running: boolean;
  supervisor_alive: boolean;
  current: { task_id?: string; role?: string; label?: string };
  quota: {
    provider_error_message?: string;
    provider_error_code?: string;
    at?: string;
  };
  tasks: TaskSummary[];
  progress: {
    completed: number;
    discovery: number;
    validation: number;
    test: number;
    experiences: number;
  };
  mode: string;
  milestones: {
    audit: boolean;
    candidates: number;
    expected_candidates: number;
    stage: string;
  };
  k: number;
  model: string;
  usage: { solver: ActorUsage; optimizer: ActorUsage };
  selection: { candidate?: string; status: string } | null;
  validation: MatrixRow[] | null;
  test: MatrixRow[] | null;
  recovery: { stage?: string; at?: string };
  started_at?: string;
}
export interface Stage {
  id: string;
  status: string;
  selected: boolean;
  notes: string;
  error: string;
  fallback: boolean;
  kept_base: boolean;
  changed: string[];
  files: string[];
  seconds?: number;
  usage: {
    total_tokens?: number;
    input_tokens?: number;
    output_tokens?: number;
  };
  digest?: string;
  session_id?: string;
  has_execution: boolean;
  parent?: string;
}
export interface TaskDetail {
  revision: string;
  task: { id: string; question: string; domain: string };
  k: number;
  status: string;
  nodes: Stage[];
  selection: {
    chosen_label?: string;
    why?: string;
    ok?: boolean;
    selected_at?: string;
    n_candidates?: number;
  };
  experience: {
    cue?: string;
    lesson?: string;
    evidence?: string;
    confidence?: string;
    edits?: string;
  } | null;
  experience_saved: boolean;
  errors: string[];
}
export interface Artifact {
  text?: string;
  missing?: boolean;
  truncated?: boolean;
  files?: { path: string; type: string; diff: string }[];
  parent?: string;
  node?: string;
}
