export type ModelUsage = {requests:number;input_tokens:number;output_tokens:number;total_tokens:number;cached_input_tokens:number;missing_usage:number;failed_requests:number;request_seconds:number;timed_requests:number;retries:number;models:string[]};
export type BatchProgress = {id:string;scope:string;version:string;total:number;task_count:number;completed:number;failed:number;started_at:number;updated_at:number;active:{task_id:string;trial:number;started_at:number}[]};
export type Telemetry = {checked_at:number;started_at:number|null;finished_at:number|null;elapsed_seconds:number|null;last_activity_at:number|null;usage:Record<'execution'|'analysis'|'evaluation',ModelUsage>;progress:{iteration:number;reviewed_rounds:number;active_jobs:{id:string;started_at:number|null}[];batch:BatchProgress|null;completed_trials:number;failed_trials:number;batch_count:number}};
export function duration(seconds:number|null|undefined) {
  if(seconds==null)return '—';
  const n=Math.max(0,Math.floor(seconds));
  return n>=3600 ? `${Math.floor(n/3600)}h ${Math.floor(n%3600/60)}m` : n>=60 ? `${Math.floor(n/60)}m ${n%60}s` : `${n}s`;
}
export function jobLabel(id:string) {
  if(id.includes('channel-preflight'))return 'Checking component loading';
  if(id.includes('confirm'))return 'Confirming candidate';
  if(id.startsWith('rollout-'))return 'Evaluating candidate';
  if(id.includes('harness-editor'))return 'Preparing candidate';
  if(id.startsWith('main-'))return 'Reviewing evidence';
  if(id.startsWith('analyzer'))return 'Analyzing results';
  if(id.startsWith('experience'))return 'Extracting experience';
  if(id.startsWith('explorer'))return 'Discovering improvements';
  return 'Analyzing experiment';
}
