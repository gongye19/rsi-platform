"use client";
import {useEffect,useState} from 'react';
import {Check,Loader2} from 'lucide-react';
import {type Run} from '@/lib/console-types';
import {DEMO_MODE} from '@/lib/branding';
import {duration,jobLabel,type ModelUsage} from '@/lib/telemetry';

const activeStates=new Set(['running','stopping','queued']);
export default function ExperimentProgress({run,connected}:{run:Run;connected:boolean}) {
  const [now,setNow]=useState(0);
  const active=activeStates.has(run.state);
  useEffect(()=>{
    const first=setTimeout(()=>setNow(Date.now()/1000),0);
    if(!active)return ()=>clearTimeout(first);
    const timer=setInterval(()=>setNow(Date.now()/1000),1000);
    return ()=>{clearTimeout(first);clearInterval(timer);};
  },[active]);
  const t=run.telemetry;
  const p=t?.progress;
  const batch=p?.batch;
  const elapsed=active && connected && t?.started_at && now ? now-t.started_at : t?.elapsed_seconds;
  const phase=run.phase?.id || 'baseline';
  const stageIndex=run.state==='succeeded'?4:phase==='test'?3:phase==='evolution'||phase==='finalized'?2:['discovery','experience','analysis'].includes(phase)?1:0;
  const jobs=p?.active_jobs || [];
  const activity=active ? batch?.active.length ? `Evaluating ${batch.scope} · ${batch.version}` : jobs.length ? jobLabel(jobs.at(-1)!.id) : run.phase?.label || 'Waiting for worker' : run.state==='succeeded'?'Completed':run.state==='draft'?'Ready to start':run.state;
  const last=t?.last_activity_at;
  return <section className="experiment-observation" aria-label="Live experiment progress">
    <div className="run-stage-track" aria-label="Experiment stages">{['TRAIN baseline','Discovery & analysis','TRAIN evolution','TEST evaluation'].map((label,index)=><div key={label} className={index<stageIndex?'done':index===stageIndex?'current':''}>{index<stageIndex?<Check size={14}/>:<span className="stage-marker"/>}<span>{label}</span></div>)}</div>
    <div className="run-progress-heading"><strong>{active && connected && <Loader2 size={16} className="animate-spin"/>}{activity}</strong><span>{active ? connected?(DEMO_MODE?'Simulated · updates every 3s':'Live · updates every 3s'):'Disconnected · last received data':DEMO_MODE?'Simulated results':'Recorded results'} · <b>{duration(elapsed)}</b> elapsed</span></div>
    <div className="run-progress-detail">
      <span>{p?.iteration?`Round ${String(p.iteration).padStart(2,'0')} · ${p.reviewed_rounds} reviewed`:active?'Preparing baseline':'No optimization rounds yet'}</span>
      {batch && <span>{batch.completed} / {batch.total} trials · {batch.active.length} active{batch.failed?` · ${batch.failed} errors`:''}</span>}
      {!!p?.completed_trials && <span>{p.completed_trials} evaluated trials</span>}
      {last && <time dateTime={new Date(last*1000).toISOString()}>Last output {new Date(last*1000).toLocaleTimeString('en-GB')}</time>}
    </div>
    {batch && active && <div className="run-batch-meter" role="progressbar" aria-label="Current evaluation batch" aria-valuemin={0} aria-valuemax={batch.total} aria-valuenow={batch.completed}><span style={{width:`${Math.min(100,batch.completed/batch.total*100)}%`}}/></div>}
    {active && !!batch?.active.length && <div className="run-active-tasks">{batch.active.map(task=><span key={`${task.task_id}-${task.trial}`}>{task.task_id.split('/').at(-1)} <small>trial {task.trial+1} · {duration(now?now-task.started_at:null)}</small></span>)}</div>}
    <div className="run-usage-grid"><Usage label="Execution model" usage={t?.usage.execution} model={run.configuration?.models?.execution?.model}/><Usage label="Analysis model" usage={t?.usage.analysis} model={run.configuration?.models?.analysis?.model}/>{!!t?.usage.evaluation.requests && <Usage label="Evaluation model" usage={t.usage.evaluation}/>}</div>
    {!!t && Object.values(t.usage).some(u=>u.missing_usage>0) && <p className="run-usage-note">Some requests did not return usage. Token totals include reported usage only.</p>}
  </section>;
}
function Usage({label,usage,model}:{label:string;usage?:ModelUsage;model?:string}) {
  const observed=!!usage?.requests;
  return <div className="run-model-usage"><div><span>{label}</span><strong title={usage?.models.join(', ') || model}>{model || usage?.models.join(', ') || '—'}</strong></div><b title="Provider-reported usage, including cached input tokens">{observed?usage.total_tokens.toLocaleString('en-US'):'—'} <small>tokens</small></b><p title={usage?.timed_requests ? "API time sums request durations, including waiting/retries; parallel calls overlap." : "Historical API time was not recorded."}>{observed?<><span>{usage.input_tokens.toLocaleString('en-US')} in · {usage.output_tokens.toLocaleString('en-US')} out</span><span>{usage.requests} requests{usage.timed_requests?` · ${duration(usage.request_seconds)} API time`:''}{usage.failed_requests?` · ${usage.failed_requests} failed`:''}{usage.retries?` · ${usage.retries} retries`:''}</span></>:'Waiting for reported usage'}</p></div>;
}
