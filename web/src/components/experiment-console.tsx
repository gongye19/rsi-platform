"use client";
import {useCallback,useEffect,useRef,useState} from 'react';
import {ArrowRight, Check, FlaskConical, Loader2, RefreshCw, Square, WifiOff} from 'lucide-react';
import {Button} from '@/components/ui/button';
import ExperimentList, {RunStatus as Status} from './experiment-list';
import ComponentStudio from './component-studio';
import ExperimentConfiguration from './experiment-configuration';
import {launchRun} from '@/lib/launch-run';
import {Sheet,SheetContent,SheetHeader,SheetTitle,SheetDescription} from '@/components/ui/sheet';
import {componentLabels,counts,metric,platformRead,PlatformError,type Options,type Run,type Settings} from '@/lib/console-types';
import {PLATFORM_NAME,DEMO_MODE} from '@/lib/branding';
import './experiment-console.css';
const activeStates = new Set(['queued','running','stopping']);
export default function ExperimentConsole() {
  const mainRef = useRef<HTMLElement>(null);
  const configurationTrigger = useRef<HTMLElement | null>(null);
  const [runs,setRuns] = useState<Run[]>([]);
  const [selected,setSelected] = useState('');
  const [options,setOptions] = useState<Options | null>(null);
  const [profiles,setProfiles] = useState<string[]>([]);
  const [configuration,setConfiguration] = useState<'new' | 'saved' | null>(null);
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
        if (current) return current;
        const routeRun = new URLSearchParams(window.location.search).get('run');
        return routeRun || value.find(row => activeStates.has(row.state))?.id || value.find(row => row.selected_version)?.id || value[0]?.id || '';
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
    setSelected(id);setError('');setNotice('');
    mainRef.current?.scrollTo({top:0});
    const url = new URL(window.location.href);
    if (id) url.searchParams.set('run',id); else url.searchParams.delete('run');
    window.history.replaceState(null,'',url);
  }
  function openConfiguration(mode: 'new' | 'saved') {configurationTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;setConfiguration(mode);}
  function newExperiment() {openConfiguration('new');setConfigError('');void loadChoices();}
  async function deleteExperiment(id:string) {
    if (busy) return false;
    setBusy(true);setError('');setNotice('');
    try {
      await platformRead('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'delete',run_id:id})});
      setRuns(current => current.filter(row => row.id !== id));
      if (selected === id) select(runs.find(row => row.id !== id)?.id || '');
      await refresh();return true;
    } catch(e) {setError((e as Error).message);return false;} finally {setBusy(false);}
  }
  async function action(kind: string) {
    if (!run || busy) return;
    setBusy(true);setError('');setNotice('');
    try {await platformRead('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:kind,run_id:run.id})});await refresh();setNotice(kind === 'stop' ? 'Stop requested. Evidence will be preserved.' : (DEMO_MODE ? 'Demo run started. No model or business service is called.' : 'Run queued. The worker will continue from its recorded state.'));}
    catch(e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function submit(profile: string,settings: Settings) {
    if (busy) return;
    setBusy(true);setConfigError('');setError('');setNotice('');
    const identity = 'exp-'+new Date().toISOString().replace(/\D/g,'').slice(0,14)+'-'+crypto.randomUUID().slice(0,8);
    let created = false;
    try {
      await launchRun({profile,run_id:identity,settings,start:true},async () => {created=true;setConfiguration(null);select(identity);await refresh();});
      await refresh();setNotice(DEMO_MODE ? 'Demo run started. Progress and results are simulated in this browser.' : 'Run queued. This view now follows the worker.');
    } catch(e) {
      // Do not retry creation automatically: an uncertain response can already
      // have persisted the run. Recover by the known client-generated identity.
      if (!created && (!(e instanceof PlatformError) || e.status >= 500)) {try {await platformRead('?'+new URLSearchParams({run:identity}));created=true;}catch {}}
      if (created) {setConfiguration(null);select(identity);await refresh();setError(`Run ${identity} was saved. ${(e as Error).message} Inspect its status before trying again.`);}
      else setConfigError((e as Error).message);
    } finally {setBusy(false);}
  }
  const phase = run?.phase?.label || (run?.stage ? run.stage.replaceAll('_',' ') : 'Not started');
  return <div className="experiment-console">
    <header className="console-topbar"><a className="console-brand" href="/experiments">{PLATFORM_NAME}</a><span className="console-topbar-divider"/><span className="console-breadcrumb">Experiments</span><div className="console-topbar-right">{DEMO_MODE && <span className="console-demo-label">Demo · Simulated data</span>}<span className="console-runtime">OpenCode 1.18.32</span></div></header>
    <div className="console-body"><ExperimentList runs={runs} selected={selected} loading={loading} busy={busy} onSelect={select} onNew={newExperiment} onDelete={deleteExperiment}/>
      <main ref={mainRef} className="console-main">
        <div className="console-page-heading"><div><h1>{run?.id || selected || 'Experiments'}{run && <Status state={run.state}/>}</h1><p>{run ? <>{run.configuration?.benchmark || 'Benchmark'} · <time dateTime={new Date(run.created*1000).toISOString()} title={new Date(run.created*1000).toLocaleString('en-GB')}>{new Date(run.created*1000).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric'})}</time>{activeStates.has(run.state) && <span className="console-phase"> · {phase}</span>}</> : (DEMO_MODE ? 'Explore an evolution workflow with simulated data.' : 'Configure an experiment to start a real evolution run.')}</p></div><div className="console-header-actions">{run && <Button variant="ghost" onClick={() => openConfiguration('saved')}>Run settings</Button>}{!run && <Button className="console-new-button" disabled={busy} onClick={newExperiment}>New experiment</Button>}<Button variant="outline" size="icon" aria-label="Refresh console" onClick={() => {setError('');void refresh();if (!options) void loadChoices();}}><RefreshCw size={15}/></Button>{run && !run.read_only && <>{run.state === 'draft' && <Button disabled={busy} onClick={() => void action('start')}>{busy ? <Loader2 size={14} className="animate-spin"/> : <ArrowRight size={14}/>}Start run</Button>}{activeStates.has(run.state) && <Button variant="outline" disabled={busy || run.state === 'stopping'} onClick={() => void action('stop')}><Square size={13}/>{run.state === 'stopping' ? 'Stopping…' : 'Stop run'}</Button>}{['failed','interrupted','stopped'].includes(run.state) && <Button disabled={busy} onClick={() => void action('resume')}><ArrowRight size={14}/>Resume run</Button>}</>}</div></div>
        {(!connected || error) && <div className="console-alert console-main-alert" role="alert">{!connected && <WifiOff size={14}/>}<span>{error || connectionError || 'Connection interrupted. Showing the last received records.'}</span></div>}{notice && <div className="console-notice" role="status"><Check size={14}/><span>{notice}</span></div>}
        {run ? <>
          <section className="console-metrics" aria-label="Experiment summary">
            <div title={counts(run.baseline_metrics)}><span>TRAIN baseline</span><strong>{metric(run.baseline_metrics)}</strong></div>
            <div title={run.tests?.selected ? `${counts(run.tests.selected.metrics)} · ${run.tests.selected.repeats ?? '?'} per task` : 'No TEST result yet'}><span>Final TEST</span><strong>{metric(run.tests?.selected?.metrics)}</strong></div>
            <div title={run.budget?.remaining != null ? `${run.budget.remaining} TRAIN sessions remaining` : 'Not initialized'}><span>Budget</span><strong>{run.budget?.total != null ? <>{run.budget.used}<em> / {run.budget.total}</em></> : '—'}</strong></div>
          </section>
          <section className="console-workspace" aria-label="Experiment evolution">
            <ComponentStudio key={run.id} run={run.id} live={activeStates.has(run.state) && connected} revision={revision}/>
          </section>
          {run.state === 'failed' && <p className="console-bottom-note">{run.read_only ? 'Imported run ended with an error.' : run.error || 'The run stopped with an error.'} Review the failure before resuming.</p>}
        </> : loading ? <div className="console-empty"><Loader2 className="animate-spin"/>Loading experiments…</div> : <div className="console-empty"><FlaskConical size={28}/><h2>{selected ? 'Experiment not found' : 'Start your first experiment'}</h2><p>Choose models, components and an evolution budget to begin.</p><Button onClick={newExperiment}>New experiment</Button></div>}
      </main></div>
    <Sheet open={configuration !== null} onOpenChange={open => {if (!open && !busy) setConfiguration(null);}}>
      <SheetContent className="console-config-sheet" overlayClassName="console-config-overlay" showCloseButton={!busy} onCloseAutoFocus={event => {event.preventDefault();configurationTrigger.current?.focus();}}>
        <SheetHeader><SheetTitle>{configuration === 'new' ? 'New experiment' : 'Run settings'}</SheetTitle><SheetDescription>{configuration === 'new' ? 'Choose the settings for this run.' : 'The settings used by this experiment are read only.'}</SheetDescription></SheetHeader>
        {configuration === 'new' ? <ExperimentConfiguration options={options} profiles={profiles} busy={busy} error={configError} onSubmit={submit} onCancel={() => setConfiguration(null)}/> : run && <SavedConfiguration run={run} options={options}/>}
      </SheetContent>
    </Sheet>
  </div>;
}
function SavedConfiguration({run,options}: {run: Run;options: Options | null}) {
  const config = run.configuration || {};
  return <section className="saved-configuration"><div className="saved-grid"><div><span>Final Harness</span><strong>{run.selected_version || 'Not finalized'}</strong></div><div><span>Benchmark</span><strong>{config.benchmark || 'Unavailable'}</strong></div><div><span>Task domain</span><strong>{config.dataset?.domain && config.dataset.domain !== 'all' ? config.dataset.domain.replace(/^group:/,'').replaceAll('_',' ') : 'All task groups'}</strong></div><div><span>Training tasks</span><strong>{config.dataset_selection?.train.length ?? (config.dataset?.train_count || 'Full split')}</strong></div><div><span>Test tasks</span><strong>{config.dataset_selection?.test.length ?? (config.dataset?.test_count || 'Full split')}</strong></div><div><span>Execution model</span><strong>{config.models?.execution?.managed_by ? 'Managed by business agent' : config.models?.execution?.model || 'Unavailable'}</strong></div><div><span>Analysis model</span><strong>{config.models?.analysis?.model || 'Unavailable'}</strong></div><div><span>Initial Harness</span><strong>{config.initial_harness || 'Empty starting Harness'}</strong></div><div><span>Frozen TEST evaluation</span><strong>{config.full_evaluation ? 'Enabled' : 'Disabled'}</strong></div></div><h3>Allowed components <small>{config.components?.allowed.length ?? 0} / 16</small></h3><div className="saved-components">{config.components?.allowed.map(id => <span key={id}><Check size={12}/>{componentLabels[id] || id}</span>)}</div>{!!config.components?.denied.length && <p>Not allowed: {config.components.denied.map(id => componentLabels[id] || id).join(', ')}</p>}<h3>Declaration-only components <small>{(config.components?.proposal_only ?? options?.proposal_only ?? []).length} / 5</small></h3><div className="saved-components">{(config.components?.proposal_only ?? options?.proposal_only ?? []).map(id=><span key={id}><Check size={12}/>{componentLabels[id] || id}</span>)}</div><p>Recommendations only. These components cannot be edited automatically.</p><h3>Evolution settings</h3><div className="saved-parameters">{Object.entries(config.parameters || {}).filter(([key]) => ['HAI_TOTAL_CREATION_BUDGET','HAI_TRAIN_ROLLOUT_REPEATS','HAI_TEST_ROLLOUT_REPEATS','HAI_MAX_ROLLOUT_CONCURRENCY','HAI_MAX_ANALYSIS_CONCURRENCY','HAI_PROVIDER_MAX_CONCURRENCY'].includes(key)).map(([key,value]) => <div key={key}><span>{options?.parameters.find(p => p.key === key)?.label || key.replace(/^HAI_/,'').replaceAll('_',' ').toLowerCase()}</span><strong>{String(value)}</strong></div>)}</div></section>;
}
