"use client";
import {useCallback, useEffect, useMemo, useState} from 'react';
import {ChevronDown, ExternalLink, GitBranch, Info, RefreshCw} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Select, SelectTrigger, SelectValue, SelectContent, SelectItem} from '@/components/ui/select';
import {Popover, PopoverContent, PopoverTrigger} from '@/components/ui/popover';
import {Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription} from '@/components/ui/sheet';
import ComponentTree from './component-tree';
import RoundOutcomeChart from './round-outcome-chart';
import EvolutionWorkspace from './evolution-workspace';
import {harnessViews} from '@/lib/harness-views';
import {evolutionRounds} from '@/lib/component-layout';
import {activeAt, decisionAt, decisionLabels, type ComponentHistory} from '@/lib/component-types';
import {componentLabels} from '@/lib/console-types';
import './component-studio.css';
export default function ComponentStudio({run, live, revision, onOpenArtifacts}: {run: string; live: boolean; revision: number; onOpenArtifacts: () => void}) {
  const [data,setData] = useState<ComponentHistory | null>(null);
  const [error,setError] = useState('');
  const [selected,setSelected] = useState('');
  const [hoveredRound,setHoveredRound] = useState<number | null>(null);
  const [focusedRound,setFocusedRound] = useState<number | null>(null);
  const [focusRevision,setFocusRevision] = useState(0);
  const [inspectedId,setInspectedId] = useState('');
  const [panel,setPanel] = useState(false);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await fetch('/api/evolution?' + new URLSearchParams({run}),{cache:'no-store',signal});
      const value = await response.json();
      if (!response.ok) throw new Error(value.error || 'Unable to load component lineage.');
      if (signal?.aborted) return;
      setData({...value,components:value.components.map((c: ComponentHistory['components'][number]) => ({...c,name:componentLabels[c.id] || c.id}))}); setError('');
    } catch(e) {if (!signal?.aborted) setError((e as Error).message);}
  },[run]);
  useEffect(() => {
    const abort = new AbortController();
    const first = setTimeout(() => void refresh(abort.signal), 0);
    return () => {abort.abort(); clearTimeout(first);};
  },[refresh,revision]);
  const step = Math.max(0,(data?.steps.length || 1)-1);
  const active = data && data.context.initial_ready !== false ? activeAt(data,step) : undefined;
  const views = useMemo(() => data && data.context.initial_ready !== false ? harnessViews(data,step) : [],[data,step]);
  const rounds = useMemo(() => data ? evolutionRounds(data) : [],[data]);
  const linkedRound = hoveredRound ?? focusedRound ?? rounds.at(-1)?.round ?? 0;
  const inspected = views.find(v => v.id === inspectedId) || views.find(v => v.bundleIds.includes(active?.id || '')) || views.at(-1);
  const bundle = inspected?.bundleIds.includes(active?.id || '') ? active : inspected?.bundle;
  const version = data?.versions.find(v => v.id === selected);
  const component = data?.components.find(c => c.id === version?.component_id);
  const bundleId = data?.bundles.findLast(b => b.components[version?.component_id || ''] === version?.id)?.id;
  const decision = data && version ? decisionAt(data,version.id,step) || data.decisions.filter(d => d.scope === 'bundle' && d.version_id === bundleId && d.step <= step).at(-1) : undefined;
  const choose = useCallback((id: string) => {setSelected(id);setPanel(true);},[]);
  const focus = useCallback((round: number) => {setFocusedRound(round);setFocusRevision(v => v+1);setHoveredRound(null);},[]);
  const ready = data?.context?.initial_ready !== false;
  return <div className={live ? "ce-root ce-console-embedded ce-follow-live" : "ce-root ce-console-embedded"}>
    <div className="ce-experiment">
      <div className="ce-controls"><span className="studio-mode-label"><GitBranch size={14}/>{live ? 'Live execution' : 'Recorded execution'}</span><span className="ce-harness-picker">Harness<Select value={inspected?.id || ''} disabled={!views.length} onValueChange={setInspectedId}><SelectTrigger aria-label="Inspect Harness"><SelectValue placeholder="No snapshot yet"/></SelectTrigger><SelectContent>{views.map(v => <SelectItem value={v.id} key={v.id}>{v.label} · {v.bundle.id}{v.bundleIds.includes(active?.id || '') ? ' · Selected' : ''}</SelectItem>)}</SelectContent></Select></span><Popover><PopoverTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Measurement information"><Info size={14}/></Button></PopoverTrigger><PopoverContent className="ce-record-popover" align="end"><p>Scores describe the retained TRAIN configuration. Candidate task subsets may differ. Final TEST results are shown in the console summary.</p><p>Each metric has its own axis. Reused measurements are identified; missing values stay empty. Bundle selection does not establish an individual component’s causal contribution.</p></PopoverContent></Popover><Button variant="ghost" size="icon-sm" aria-label="Refresh lineage" onClick={() => void refresh()}><RefreshCw size={14}/></Button></div>
      <div className="ce-experiment-legend"><span><i className="ce-key-normal"/>Version</span><span><i className="ce-key-rejected">×</i>Not retained</span><span><i className="ce-key-trunk"/>Derived version</span><span><i className="ce-key-carry"/>Unchanged version</span></div>
      {error && <div className="ce-error" role="alert">{error}<Button variant="ghost" size="sm" onClick={() => void refresh()}>Retry</Button></div>}
      {!data ? <div className="ce-loading"><GitBranch size={22}/>{error ? 'Lineage unavailable' : 'Loading execution records…'}</div> : !ready ? <div className="ce-loading console-lineage-wait"><GitBranch size={28}/><strong>Waiting for the initial snapshot</strong><span>Lineage will appear when the worker freezes the actual starting Harness.</span></div> : <>
        <EvolutionWorkspace left={<section className="ce-lineages"><div className="ce-result-heading"><h2 className="ce-plot-title">Component lineage <span className="ce-component-count">{data.components.length}</span></h2><span className="ce-round-chip"><i/>{linkedRound ? `Round ${linkedRound}` : 'Baseline'}</span></div><div className="ce-tree-scroll" role="region" tabIndex={0} aria-label="Component lineage, horizontally scrollable"><ComponentTree data={data} step={step} selected={selected} configuration={bundle?.components} selectedRound={linkedRound} focusedRound={focusedRound} focusRevision={focusRevision} onHoverRound={setHoveredRound} onRound={focus} onSelect={choose} followLive={live}/></div></section>} right={<section className="ce-results"><div className="ce-result-heading"><h2 className="ce-plot-title">Retained configuration results</h2><span className="ce-round-chip"><i/>{linkedRound ? `Round ${linkedRound}` : 'Baseline'}</span></div><RoundOutcomeChart data={data} step={step} activeRound={linkedRound} onHoverRound={setHoveredRound} onRound={focus}/></section>}/>
        <div className="console-lineage-footnote"><span>TRAIN measurements · {rounds.length} recorded {rounds.length === 1 ? 'round' : 'rounds'}</span><span>Click a version to inspect its snapshot</span></div>
      </>}
    </div>
    <Sheet open={panel && !!version} onOpenChange={setPanel}><SheetContent className="ce-evidence"><SheetHeader><SheetTitle>{component?.name} <code>{version?.label}</code></SheetTitle><SheetDescription>Recorded component snapshot and adoption evidence.</SheetDescription></SheetHeader>{version && data && <><div className="ce-version-meta"><span>{version.parent_id ? `Parent: ${data.versions.find(v => v.id === version.parent_id)?.label}` : 'Initial snapshot'}</span><span>Round {version.round}</span><span>{version.digest.slice(0,10)}</span></div><div className={`ce-verdict ${decision?.outcome || 'unknown'}`}><strong>{decision ? decisionLabels[decision.outcome] : version.step === 0 ? 'Initial version' : 'No adoption decision recorded'}</strong>{decision?.reason && <p>{decision.reason}</p>}{decision?.scope === 'bundle' && <small>Decision scope: complete Harness, not an independent component test.</small>}</div><div className="ce-evidence-scroll">{version.files.length ? version.files.map(file => <details key={file.path}><summary>{file.path}<ChevronDown size={12}/></summary><pre>{file.diff}</pre></details>) : <p>This component has no custom content in this snapshot.</p>}{decision?.evidence && <details><summary>Decision evidence<ChevronDown size={12}/></summary><p>{decision.evidence}</p></details>}</div><Button variant="outline" onClick={() => {setPanel(false);onOpenArtifacts();}}><ExternalLink size={14}/>View run traces and artifacts</Button></>}</SheetContent></Sheet>
  </div>;
}
