"use client";
import {useCallback,useEffect,useState} from 'react';
import {Activity, ArrowRight, Box, Check, ChevronRight, FlaskConical, GitBranch, Layers3, Loader2, Plus, RefreshCw, Settings2, Square, Terminal, WifiOff, LayoutList, CircleDot, FileClock, CircleCheck} from 'lucide-react';
import {Button} from '@/components/ui/button';
import ExperimentDirectory, {RunStatus as Status} from './experiment-directory';
import ComponentStudio from './component-studio';
import ExperimentConfiguration from './experiment-configuration';
import {launchRun} from '@/lib/launch-run';
import {RunActivity,RunArtifacts} from './experiment-records';
import {componentLabels,counts,metric,platformRead,PlatformError,stateLabels,type Options,type Run,type Settings} from '@/lib/console-types';
import {PLATFORM_NAME} from '@/lib/branding';
import './experiment-console.css';
const activeStates = new Set(['queued','running','stopping']);
export default function ExperimentConsole() {
  const [runs,setRuns] = useState<Run[]>([]);
  const [selected,setSelected] = useState('');
  const [options,setOptions] = useState<Options | null>(null);
  const [profiles,setProfiles] = useState<string[]>([]);
  const [configOpen,setConfigOpen] = useState(false);
  const [tab,setTab] = useState('overview');
  const [directoryFilter,setDirectoryFilter] = useState('all');
  const [busy,setBusy] = useState(false);
  const [error,setError] = useState('');
  const [configError,setConfigError] = useState('');
  const [notice,setNotice] = useState('');
  const [connectionError,setConnectionError] = useState('');
  const [connected,setConnected] = useState(true);
  const [loading,setLoading] = useState(true);
  const [revision,setRevision] = useState(0);
  const run = runs.find(row => row.id === selected);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const value = await platformRead<Run[]>('',{signal});
      if (signal?.aborted) return;
      setRuns(value);setConnected(true);setConnectionError('');setLoading(false);setRevision(v => v+1);
      setSelected(current => {
        if (current === '__directory') return current;
        if (current) return current;
        const routeRun = new URLSearchParams(window.location.search).get('run');
        return routeRun || '__directory';
      });
    } catch(e) {if (!signal?.aborted) {setConnected(false);setConnectionError((e as Error).message);setLoading(false);}}
  },[]);
  const loadChoices = useCallback(async (signal?: AbortSignal) => {
    try {const [p,o] = await Promise.all([platformRead<string[]>('?profiles=1',{signal}),platformRead<Options>('?options=1',{signal})]);if (!signal?.aborted) {setProfiles(p);setOptions(o);setConfigError('');}}
    catch(e) {if (!signal?.aborted) setConfigError((e as Error).message);}
  },[]);
  useEffect(() => {
    const abort = new AbortController();let timer: ReturnType<typeof setTimeout>;
    async function poll() {await refresh(abort.signal);if (!abort.signal.aborted) timer=setTimeout(() => void poll(),4000);}
    void poll();
    const choices = setTimeout(() => void loadChoices(abort.signal),0);
    return () => {abort.abort();clearTimeout(timer);clearTimeout(choices);};
  },[refresh,loadChoices]);
  function select(id: string) {
    setSelected(id);setTab('overview');setError('');setNotice('');
    const url = new URL(window.location.href);
    if (id === '__directory') url.searchParams.delete('run'); else url.searchParams.set('run',id);
    window.history.replaceState(null,'',url);
  }
  function newExperiment() {setConfigError('');setConfigOpen(true);if (!options) void loadChoices();}
  async function action(kind: string) {
    if (!run || busy) return;
    setBusy(true);setError('');setNotice('');
    try {await platformRead('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:kind,run_id:run.id})});await refresh();setNotice(kind === 'stop' ? 'Stop requested. Evidence will be preserved.' : 'Run queued. The worker will continue from its recorded state.');}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function submit(profile: string,id: string,settings: Settings,start: boolean) {
    if (busy) return;
    setBusy(true);setConfigError('');setError('');setNotice('');
    const identity = id.trim() || 'exp-'+new Date().toISOString().replace(/\D/g,'').slice(0,14)+'-'+crypto.randomUUID().slice(0,8);
    let created = false;
    try {
      await launchRun({profile,run_id:identity,settings,start},async () => {created=true;select(identity);await refresh();});
      await refresh();setConfigOpen(false);setNotice(start ? 'Run queued. This view now follows the worker.' : 'Draft saved. Its configuration is frozen; start it when ready.');
    } catch(e) {
      // Do not retry creation automatically: an uncertain response can already
      // have persisted the run. Recover by the known client-generated identity.
      if (!created && (!(e instanceof PlatformError) || e.status >= 500)) {try {await platformRead('?'+new URLSearchParams({run:identity}));created=true;}catch {}}
      if (created) {select(identity);await refresh();setConfigOpen(false);setError(`Run ${identity} was saved. ${(e as Error).message} Inspect its status before trying again.`);}
      else setConfigError((e as Error).message);
    } finally {setBusy(false);}
  }
  const phase = run?.phase?.label || (run?.stage ? run.stage.replaceAll('_',' ') : 'Not started');
  return <div className="experiment-console">
    <header className="console-topbar"><a className="console-brand" href="/experiments"><span><Layers3 size={18}/></span>{PLATFORM_NAME}</a><span className="console-topbar-divider"/><button className="console-breadcrumb" onClick={() => {setDirectoryFilter('all');select('__directory');}}>Experiments</button>{run && <><ChevronRight size={13}/><span className="console-current-run">{run.id}</span></>}<div className="console-topbar-right"><span className="console-environment"><i/>Local workspace</span><span className="console-runtime">OpenCode 1.18.32</span></div></header>
    <div className="console-body"><aside className="console-sidebar"><div className="console-workspace-identity"><span className="workspace-monogram">S</span><div><strong>Research workspace</strong><small>Agent evolution</small></div></div><div className="console-sidebar-heading">WORKSPACE</div><nav className="console-primary-nav" aria-label="Workspace">{[{id:'all',label:'All experiments',icon:LayoutList,count:runs.length},{id:'active',label:'In progress',icon:CircleDot,count:runs.filter(r => activeStates.has(r.state)).length},{id:'draft',label:'Drafts',icon:FileClock,count:runs.filter(r => r.state === 'draft').length},{id:'completed',label:'Completed',icon:CircleCheck,count:runs.filter(r => r.state === 'succeeded').length}].map(item => <button key={item.id} aria-label={item.label} title={item.label} aria-current={!run && directoryFilter === item.id ? 'page' : undefined} onClick={() => {setDirectoryFilter(item.id);select('__directory');}}><item.icon size={16}/><span>{item.label}</span><small>{item.count}</small></button>)}</nav><div className="console-sidebar-context"><span className="console-sidebar-heading">WORKFLOW</span><ol><li>Configure a run</li><li>Evaluate & evolve</li><li>Review the evidence</li></ol></div><div className="console-sidebar-footer"><ShieldLabel/><span>Evidence and versions are stored here.</span></div></aside>
      <main className="console-main">
        {!run && selected === '__directory' ? <div className="console-page-heading directory-page-heading"><div><div className="console-eyebrow">RESEARCH / EXPERIMENTS</div><h1>Experiments<span className="directory-total">{runs.length}</span></h1><p>Configure, evolve, and compare your agent harnesses.</p></div><div className="console-header-actions"><Button variant="outline" size="icon" aria-label="Refresh console" onClick={() => void refresh()}><RefreshCw size={15}/></Button><Button onClick={newExperiment}><Plus size={15}/>New experiment</Button></div></div> : <div className="console-page-heading"><div><button className="console-back" onClick={() => {setDirectoryFilter('all');select('__directory');}}>← All experiments</button><h1>{run?.id || selected || 'Experiments'}{run && <Status state={run.state}/>}</h1><p>{run ? `${run.configuration?.benchmark || 'Benchmark'} · ${run.read_only ? 'Imported execution · read only' : `Attempt ${run.attempt}`} · ${new Date(run.created*1000).toLocaleString('en-GB')}` : 'Configure an experiment to start a real evolution run.'}</p></div><div className="console-header-actions"><Button variant="outline" size="icon" aria-label="Refresh console" onClick={() => {setError('');void refresh();if (!options) void loadChoices();}}><RefreshCw size={15}/></Button>{run && !run.read_only && <>{run.state === 'draft' && <Button disabled={busy} onClick={() => void action('start')}>{busy ? <Loader2 size={14} className="animate-spin"/> : <ArrowRight size={14}/>}Start run</Button>}{activeStates.has(run.state) && <Button variant="outline" disabled={busy || run.state === 'stopping'} onClick={() => void action('stop')}><Square size={13}/>{run.state === 'stopping' ? 'Stopping…' : 'Stop run'}</Button>}{['failed','interrupted','stopped'].includes(run.state) && <Button disabled={busy} onClick={() => void action('resume')}><ArrowRight size={14}/>Resume run</Button>}</>}<Button variant="outline" onClick={newExperiment}><Settings2 size={14}/>{run ? 'Configure new run' : 'Configure experiment'}</Button></div></div>}
        {(!connected || error) && <div className="console-alert console-main-alert" role="alert">{!connected && <WifiOff size={14}/>}<span>{error || connectionError || 'Connection interrupted. Showing the last received records.'}</span></div>}{notice && <div className="console-notice" role="status"><Check size={14}/>{notice}</div>}
        {selected === '__directory' ? <ExperimentDirectory runs={runs} filter={directoryFilter} loading={loading} onSelect={select} onNew={newExperiment}/> : run ? <>
          <section className="console-metrics" aria-label="Experiment summary"><div><span>EXECUTION STAGE</span><strong className="console-phase-value">{phase}</strong><small>{activeStates.has(run.state) ? connected ? 'Following worker checkpoints' : 'Connection lost' : stateLabels[run.state]}</small></div><div><span>TRAIN BASELINE</span><strong>{metric(run.baseline_metrics)}</strong><small>{counts(run.baseline_metrics)}</small></div><div><span>FINAL TEST</span><strong>{metric(run.tests?.selected?.metrics)}</strong><small>{run.tests?.selected ? `${counts(run.tests.selected.metrics)} · ${run.tests.selected.repeats ?? '?'} per task` : 'No TEST result yet'}</small></div><div><span>CREATION BUDGET</span><strong>{run.budget?.total != null ? <>{run.budget.used}<em> / {run.budget.total}</em></> : '—'}</strong><small>{run.budget?.remaining != null ? `${run.budget.remaining} TRAIN sessions remaining` : 'Not initialized'}</small></div><div><span>SELECTED HARNESS</span><strong>{run.selected_version || '—'}</strong><small>{run.selected_version ? run.selected_version === 'v0' ? 'Initial version retained' : 'Frozen final version' : 'Not finalized'}</small></div></section>
          <div className="console-workspace"><div className="console-tabs" role="tablist" aria-label="Experiment views">{[{id:'overview',label:'Overview',icon:GitBranch},{id:'configuration',label:'Configuration',icon:Settings2},{id:'artifacts',label:'Artifacts',icon:Terminal},{id:'activity',label:'Activity',icon:Activity}].map(item => <button role="tab" id={`tab-${item.id}`} aria-controls={`panel-${item.id}`} aria-selected={tab === item.id} tabIndex={tab === item.id ? 0 : -1} key={item.id} onClick={() => setTab(item.id)} onKeyDown={e => {if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {e.preventDefault();const ids=['overview','configuration','artifacts','activity'];const next=ids[(ids.indexOf(tab)+(e.key === 'ArrowRight' ? 1 : 3))%4];setTab(next);document.getElementById('tab-'+next)?.focus();}}}><item.icon size={14}/>{item.label}</button>)}<span className={`console-sync ${activeStates.has(run.state) && connected ? 'is-live' : ''}`}><i/>{!connected ? 'Disconnected' : activeStates.has(run.state) ? 'Live updates' : run.state === 'draft' ? 'Not started' : 'Recorded results'}</span></div>
            <div className="console-tabpanel" role="tabpanel" id={'panel-'+tab} aria-labelledby={'tab-'+tab}>
              {tab === 'overview' && <ComponentStudio key={run.id} run={run.id} live={activeStates.has(run.state) && connected} revision={revision} onOpenArtifacts={() => setTab('artifacts')}/>}
              {tab === 'configuration' && <SavedConfiguration run={run} onNew={newExperiment}/>}
              {tab === 'artifacts' && <RunArtifacts key={run.id} run={run.id} revision={revision}/>}
              {tab === 'activity' && <RunActivity key={run.id} run={run.id} revision={revision}/>}
            </div></div>
          {run.state === 'failed' && <p className="console-bottom-note">{run.read_only ? 'Imported run ended with an error.' : run.error || 'The run stopped with an error.'} Inspect Activity and the worker log in Artifacts before resuming.</p>}
        </> : loading ? <div className="console-empty"><Loader2 className="animate-spin"/>Loading experiments…</div> : selected !== '__directory' && selected ? <div className="console-empty"><FlaskConical size={32}/><h2>Experiment not found</h2><p>No execution record is available for this ID.</p><Button onClick={newExperiment}>New experiment</Button></div> : <div className="console-new-state"><div className="console-empty"><span className="console-empty-icon"><FlaskConical size={30}/></span><span className="console-eyebrow">READY WHEN YOU ARE</span><h2>Start your next experiment</h2><p>Choose models and editable components, then run the evolution workflow.<br/>Its component lineage and result curves will appear here.</p><Button onClick={() => {setConfigError('');setConfigOpen(true);if (!options) void loadChoices();}}><Plus size={15}/>Configure experiment</Button><div className="console-empty-steps"><span><Settings2 size={14}/>Configure</span><ChevronRight size={12}/><span><ArrowRight size={14}/>Run</span><ChevronRight size={12}/><span><GitBranch size={14}/>Inspect</span></div></div></div>}
      </main></div>
    <ExperimentConfiguration open={configOpen} onOpenChange={setConfigOpen} profiles={profiles} options={options} busy={busy} error={configError} onSubmit={submit}/>
  </div>;
}
function ShieldLabel() {return <span><Box size={14}/>Private experiment workspace</span>;}
function SavedConfiguration({run,onNew}: {run: Run; onNew: () => void}) {
  const config = run.configuration || {};
  return <section className="saved-configuration"><div className="saved-heading"><div><h2>Run configuration</h2><p>{run.read_only ? 'Original model receipt and source profile. Imported runs are read only.' : 'Frozen when this run was created. Changes belong to a new experiment.'}</p></div><Button variant="outline" onClick={onNew}><Plus size={14}/>New experiment</Button></div><div className="saved-grid"><div><span>Benchmark</span><strong>{config.benchmark || 'Unavailable'}</strong></div><div><span>Execution model</span><strong>{config.models?.execution?.managed_by ? 'Managed by business agent' : config.models?.execution?.model || 'Unavailable'}</strong></div><div><span>Analysis model</span><strong>{config.models?.analysis?.model || 'Unavailable'}</strong></div><div><span>Initial Harness</span><strong>{config.initial_harness || 'Empty starting Harness'}</strong></div><div><span>Frozen TEST evaluation</span><strong>{config.full_evaluation ? 'Enabled' : 'Disabled'}</strong></div></div><h3>Allowed components <small>{config.components?.allowed.length ?? 0} / 16</small></h3><div className="saved-components">{config.components?.allowed.map(id => <span key={id}><Check size={12}/>{componentLabels[id] || id}</span>)}</div><h3>Evolution settings</h3><div className="saved-parameters">{Object.entries(config.parameters || {}).map(([key,value]) => <div key={key}><span>{key.replace(/^HAI_/,'').replaceAll('_',' ').toLowerCase()}</span><strong>{String(value)}</strong></div>)}</div><details><summary>Raw configuration</summary><pre>{JSON.stringify(config,null,2)}</pre></details>{!!run.iteration_history?.length && <><h3>Adoption decisions</h3>{run.iteration_history.map(item => <div className="saved-decision" key={item.iteration}><strong>Round {item.iteration} · {item.candidate_version}</strong><span>{item.review_decision.replaceAll('_',' ')}</span><p>{item.review_rationale}</p><small>{item.evaluation_mode === 'channel_preflight' ? 'Stopped during component preflight' : `Candidate TRAIN: ${metric(item.rollout_metrics)} · ${counts(item.rollout_metrics)}`}</small></div>)}</>}</section>;
}
