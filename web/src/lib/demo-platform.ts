/** Synthetic, browser-local showcase. No HTTP calls or business data belong here. */
import {componentLabels, type Configuration, type DatasetOptions, type Options, type Preview, type Run, type Settings} from './console-types';
import {activeAt, type ComponentHistory} from './component-types';

const STORAGE_KEY = 'rsi-platform-demo-v1';
const ids = Object.keys(componentLabels).slice(0,16);
const modelRows = [
  {id:'gpt-execution',label:'GPT · Execution',model:'gpt-execution',configured:true},
  {id:'gpt-analysis',label:'GPT · Analysis',model:'gpt-analysis',configured:true},
  {id:'open-model',label:'Open model · General purpose',model:'open-model',configured:true},
];
export const demoOptions: Options = {
  benchmarks:[{id:'knowledge-qa-13',label:'Knowledge QA · 13 tasks'},{id:'service-operations',label:'Service operations'},{id:'data-analysis',label:'Data analysis'}],
  models:modelRows,components:ids.map(id=>({id,name:componentLabels[id]})),
  proposal_only:['model_provider','runtime_env','file_attachments','tool_return','diagnostic'],
  experimental_fields:['batch_tool','primary_tools','continue_loop_on_deny','mcp_timeout','disable_paste_summary'],
  parameters:[
    {key:'HAI_TOTAL_CREATION_BUDGET',label:'Creation budget',default:52,min:13,max:10000},
    {key:'HAI_TRAIN_ROLLOUT_REPEATS',label:'TRAIN repeats per task',default:1,min:1,max:20},
    {key:'HAI_TEST_ROLLOUT_REPEATS',label:'TEST repeats per task',default:1,min:1,max:20},
    {key:'HAI_MAX_ROLLOUT_CONCURRENCY',label:'Task concurrency',default:4,min:1,max:32},
    {key:'HAI_MAX_ANALYSIS_CONCURRENCY',label:'Analysis concurrency',default:2,min:1,max:16},
    {key:'HAI_PROVIDER_MAX_CONCURRENCY',label:'Provider concurrency',default:6,min:1,max:64},
    {key:'HAI_REQUEST_TIMEOUT_S',label:'Request timeout (seconds)',default:180,min:10,max:3600},
    {key:'HAI_MAX_RETRIES',label:'Maximum retries',default:2,min:0,max:10},
  ],
};
const parameters = Object.fromEntries(demoOptions.parameters.map(p=>[p.key,p.default]));
export const demoPreview: Preview = {
  benchmark:'knowledge-qa-13',benchmark_selection:'knowledge-qa-13',
  model_selection:{execution:'gpt-execution',analysis:'gpt-analysis'},
  models:{execution:{model:'gpt-execution'},analysis:{model:'gpt-analysis'}},
  components:{allowed:ids,denied:[],experimental_fields:[],proposal_only:demoOptions.proposal_only},parameters,
  dataset:{domain:'all',train_count:10,test_count:3},initial_harness:'',full_evaluation:true,readiness:'ready',business_agent:false,mode:'train',
};
type DemoStore = {runs:Run[];started:Record<string,number>;stopped:Record<string,number>};
const metrics = (score:number,tasks=13) => ({pass_at_1:score,task_count:tasks,trial_count:tasks,trial_success_count:Math.round(score*tasks)});
function configuration(settings?:Settings): Configuration {
  return settings ? {...structuredClone(settings),models:{execution:{model:settings.models.execution},analysis:{model:settings.models.analysis}}} : structuredClone(demoPreview);
}
function emptyRun(id:string,config:Configuration,now:number):Run {
  return {id,state:'draft',error:'',attempt:0,read_only:0,created:now,updated:now,configuration:config,baseline_metrics:{},tests:{},budget:{total:config.parameters?.HAI_TOTAL_CREATION_BUDGET || 52},iteration_history:[]};
}
export function seedDemoStore(now=Date.now()/1000):DemoStore {
  return {runs:[emptyRun('knowledge-qa-evolution',configuration(),now-7200),emptyRun('tool-use-study',configuration(),now-10800)],started:{'knowledge-qa-evolution':now-7100,'tool-use-study':now-10700},stopped:{}};
}
let memory:DemoStore|undefined;
function readStore():DemoStore {
  if (typeof window !== 'undefined') {
    try {const raw=window.localStorage.getItem(STORAGE_KEY);if(raw) {const parsed=JSON.parse(raw);if(Array.isArray(parsed.runs) && parsed.started && parsed.stopped) return parsed;}} catch { /* Restricted storage still supports an in-memory demo. */ }
  }
  return memory ??= seedDemoStore();
}
function writeStore(store:DemoStore) {
  memory=store;
  if(typeof window!=='undefined') {try{window.localStorage.setItem(STORAGE_KEY,JSON.stringify(store));}catch{ /* Browser-session fallback. */ }}
}
function roundCount(run:Run) {
  if(!run.configuration.components?.allowed.length) return 0;
  const total=run.configuration.parameters?.HAI_TOTAL_CREATION_BUDGET || 52;
  const repeats=run.configuration.parameters?.HAI_TRAIN_ROLLOUT_REPEATS || 1;
  return Math.max(0,Math.min(3,Math.floor(total/(13*repeats))-1));
}
function stepAt(store:DemoStore,run:Run,now:number) {
  const elapsed=store.stopped[run.id] ?? (now-(store.started[run.id] ?? now));
  return Math.max(0,Math.min(roundCount(run)*3,Math.floor(elapsed/3)));
}
/** Fabricated scores and diffs are intentionally separate from recorded experiments. */
export function buildDemoHistory(run:Run,step=9):ComponentHistory {
  const components=ids.map(id=>({id,name:componentLabels[id],description:`Demo ${componentLabels[id].toLowerCase()} configuration`,baseline_version_id:`${id}-v0`}));
  const initial=Object.fromEntries(components.map(c=>[c.id,c.baseline_version_id]));
  const history:ComponentHistory={schema_version:'1.0',id:run.id,title:'Synthetic evolution showcase',algorithm:'Harness evolution',source:'example',notice:'All data, outcomes and metrics in this public demo are simulated.',profile:{id:'demo-agent.toml',runtime:'OpenCode',version:'1.18.32'},context:{initial_ready:run.state!=='draft',domain:'Synthetic knowledge QA'},components,versions:components.map(c=>({id:c.baseline_version_id,component_id:c.id,label:'H0',parent_id:null,step:0,round:0,digest:`demo-${c.id}-initial`,present:true,files:[],notes:'Synthetic starting configuration.'})),bundles:[{id:'v0',label:'Initial Harness',step:0,round:0,components:initial,execution:{status:'completed',seconds:48,tokens:18200},metrics:{score:9/13}}],steps:[{index:0,round:0,label:'Baseline',kind:'baseline',active_bundle_id:'v0',bundle_id:'v0'}],decisions:[]};
  let active=history.bundles[0];
  const allowed=run.configuration.components?.allowed || [];
  const plans=[['skills','system_prompt'],['commands'],['tool_parameter_description','context_management']];
  const notes=[
    'Add a source-verification checklist and clarify when to retrieve supporting evidence.',
    'Try a more aggressive command template for multi-step retrieval.',
    'Clarify query parameters and preserve key evidence during context compaction.',
  ];
  for(let r=1;r<=roundCount(run);r++) {
    const proposed=plans[r-1].filter(id=>allowed.includes(id));
    if(!proposed.length && allowed.length) proposed.push(allowed[(r-1)%allowed.length]);
    const tuple={...active.components};
    for(const id of proposed) {
      const vid=`${id}-r${r}`;tuple[id]=vid;
      history.versions.push({id:vid,component_id:id,label:`H${r}`,parent_id:active.components[id],step:r*3-2,round:r,digest:`demo-${id}-revision-${r}`,present:true,files:[{path:id==='skills'?'skills/evidence-review/SKILL.md':`harness/${id}.md`,change:'modified',diff:`--- previous\n+++ candidate\n@@ Demo configuration @@\n+ ${notes[r-1]}\n+ Validate citations before returning the final answer.\n`}],notes:notes[r-1]});
    }
    const candidate={id:`candidate-0${r}`,label:`Candidate 0${r}`,step:r*3-2,round:r,components:tuple,execution:{status:'completed',seconds:r===1?43:r===2?57:38,tokens:r===1?16400:r===2?21100:14900},metrics:{score:r===1?11/13:r===2?10/13:12/13}};
    history.bundles.push(candidate);
    const accepted=r!==2;
    history.steps.push({index:r*3-2,round:r,label:`Round ${r} · Propose`,kind:'propose',bundle_id:candidate.id,active_bundle_id:active.id},{index:r*3-1,round:r,label:`Round ${r} · Evaluate`,kind:'evaluate',bundle_id:candidate.id,active_bundle_id:active.id});
    if(accepted) active=candidate;
    history.steps.push({index:r*3,round:r,label:`Round ${r} · Select`,kind:'select',bundle_id:candidate.id,active_bundle_id:active.id});
    history.decisions.push({version_id:candidate.id,step:r*3,scope:'bundle',outcome:accepted?'retained':'not_retained',reason:accepted?(r===1?'Simulated evaluation: stronger evidence coverage improves the retained Harness from 9/13 to 11/13.':'Simulated evaluation: parameter clarity and evidence preservation improve the retained Harness to 12/13, with lower time and token usage.'):'Simulated evaluation: the command candidate regresses to 10/13 and increases latency. The parent Harness is retained.',evidence:'Demonstration only. These values are fabricated, not benchmark measurements.'});
  }
  history.steps=history.steps.filter(s=>s.index<=step);
  history.versions=history.versions.filter(v=>v.step<=step);
  history.bundles=history.bundles.filter(b=>b.step<=step);
  history.decisions=history.decisions.filter(d=>d.step<=step);
  return history;
}
export function materializeDemoRun(store:DemoStore,source:Run,now=Date.now()/1000):Run {
  const run=structuredClone(source);
  if(store.started[run.id]==null) return run;
  const step=stepAt(store,run,now), rounds=roundCount(run);
  const done=now-store.started[run.id]>=Math.max(3,rounds*9+3);
  run.state=store.stopped[run.id]!=null?'stopped':done?'succeeded':'running';
  const history=buildDemoHistory({...run,state:'running'},step);
  const active=activeAt(history,step)!;
  run.attempt=Math.max(1,run.attempt);run.updated=store.started[run.id]+step*3;
  run.phase={id:done?'completed':'evolution',label:done?'Demo completed':`Simulating ${step===0?'baseline':`round ${Math.ceil(step/3)}`}`,initial_ready:true};
  const trainTasks=run.configuration.dataset?.train_count || 13;
  const testTasks=run.configuration.dataset?.test_count || 13;
  run.baseline_metrics=metrics(9/13,trainTasks);
  const total=run.budget.total || 52;
  run.budget={total,used:Math.min(total,13*(1+Math.floor(step/3))),remaining:Math.max(0,total-13*(1+Math.floor(step/3)))};
  if(done && run.state==='succeeded') {
    run.selected_version=active.id;
    if(run.configuration.full_evaluation) run.tests={initial:{metrics:metrics(8/13,testTasks),repeats:1},selected:{metrics:metrics(active.metrics.score!-(1/13),testTasks),repeats:1}};
  }
  run.iteration_history=history.decisions.map(d=>({iteration:Math.ceil(d.step/3),candidate_version:d.version_id,review_decision:d.outcome,review_rationale:d.reason,rollout_metrics:metrics(history.bundles.find(b=>b.id===d.version_id)?.metrics.score || 0),evaluation_mode:'simulated'}));
  return run;
}
export function demoHistory(id:string):ComponentHistory {
  const store=readStore(),source=store.runs.find(r=>r.id===id);
  if(!source) throw new Error('Demo experiment not found.');
  const run=materializeDemoRun(store,source);
  return buildDemoHistory(run,stepAt(store,source,Date.now()/1000));
}
export async function demoRequest<T>(query='',init?:RequestInit):Promise<T> {
  if(init?.signal?.aborted) throw new DOMException('Aborted','AbortError');
  const store=readStore(),params=new URLSearchParams(query.replace(/^\?/,''));
  const clone=(value:unknown)=>structuredClone(value) as T;
  if(init?.method==='POST') {
    const body=JSON.parse(String(init.body || '{}'));
    const found=store.runs.find(r=>r.id===body.run_id);
    if(body.action==='create') {
      if(found) throw new Error('This demo experiment already exists.');
      const selected=body.settings?.dataset;
      if(selected){const available=demoDatasetOptions(body.settings.benchmark || 'knowledge-qa-13').domains.find(row=>row.id===selected.domain);
        if(!available || !Number.isInteger(selected.train_count) || selected.train_count<5 || selected.train_count>available.train_available || !Number.isInteger(selected.test_count) || selected.test_count<1 || selected.test_count>available.test_available)throw new Error('Choose valid dataset counts for this domain.');}

      if(!/^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(body.run_id || '')) throw new Error('Invalid demo experiment ID.');
      store.runs.unshift(emptyRun(body.run_id,configuration(body.settings),Date.now()/1000));
    } else {
      if(!found) throw new Error('Demo experiment not found.');
      if(body.action==='delete') {store.runs=store.runs.filter(r=>r.id!==body.run_id);delete store.started[body.run_id];delete store.stopped[body.run_id];}
      else if(body.action==='start' || body.action==='resume') {store.started[body.run_id]=Date.now()/1000-(store.stopped[body.run_id] || 0);delete store.stopped[body.run_id];found.state='running';found.attempt++;}
      else if(body.action==='stop') {store.stopped[body.run_id]=Date.now()/1000-(store.started[body.run_id] || Date.now()/1000);found.state='stopped';}
      else throw new Error('Unsupported demo action.');
    }
    writeStore(store);return clone({ok:true,run_id:body.run_id});
  }
  if(params.get('dataset')==='1') return clone(demoDatasetOptions(params.get('benchmark') || 'knowledge-qa-13'));
  if(params.get('options')==='1') return clone(demoOptions);
  if(params.get('profiles')==='1') return clone(params.has('name')?demoPreview:['demo-agent.toml']);
  const runs=store.runs.map(r=>materializeDemoRun(store,r));
  if(params.has('run')) {const run=runs.find(r=>r.id===params.get('run'));if(!run)throw new Error('Demo experiment not found.');return clone(run);}
  return clone(runs);
}

export function demoDatasetOptions(benchmark:string):DatasetOptions {
  const pools=benchmark==='knowledge-qa-13' ? [10,3] : benchmark==='service-operations' ? [40,20] : [70,35];
  return {benchmark,cell:benchmark,grouping:'domain',minimum_train_count:5,train_available:pools[0],test_available:pools[1],
    domains:[{id:'all',label:'All task groups',train_available:pools[0],test_available:pools[1]},
      {id:'group:reporting',label:'Reporting',train_available:Math.max(5,Math.floor(pools[0]*.6)),test_available:Math.max(1,Math.floor(pools[1]*.6))},
      {id:'group:operations',label:'Operations',train_available:pools[0]-Math.max(5,Math.floor(pools[0]*.6)),test_available:pools[1]-Math.max(1,Math.floor(pools[1]*.6))}]};
}
