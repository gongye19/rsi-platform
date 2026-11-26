"use client";
import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {ChevronDown, ChevronLeft, ChevronRight, GitBranch, MoreHorizontal} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Select, SelectTrigger, SelectValue, SelectContent, SelectItem} from '@/components/ui/select';
import {Popover, PopoverContent, PopoverTrigger} from '@/components/ui/popover';
import {Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription} from '@/components/ui/sheet';
import ComponentTree from './component-tree';
import RoundOutcomeChart from './round-outcome-chart';
import {roundPage} from '@/lib/component-round-page';
import {roundSummary} from '@/lib/round-summary';
import {COMPONENT_COLORS} from '@/lib/component-types';
import {evolutionRounds} from '@/lib/component-layout';
import {decisionAt, decisionLabels, type ComponentHistory} from '@/lib/component-types';
import {componentLabels} from '@/lib/console-types';
import './component-studio.css';
export default function ComponentStudio({run, live, revision}: {run: string; live: boolean; revision: number}) {
  const evidenceTrigger = useRef<HTMLElement | null>(null);
  const studioRoot = useRef<HTMLDivElement>(null);
  const preservedScroll = useRef<{element:HTMLElement;top:number} | null>(null);
  const [view,setView] = useState<'lineage' | 'evaluation'>('lineage');
  const [data,setData] = useState<ComponentHistory | null>(null);
  const [error,setError] = useState('');
  const [selected,setSelected] = useState('');
  const [hoveredRound,setHoveredRound] = useState<number | null>(null);
  const [focusedRound,setFocusedRound] = useState<number | null>(null);
  const [inspectedId,setInspectedId] = useState('');
  const [panel,setPanel] = useState(false);
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      let value: ComponentHistory;
      if (process.env.NEXT_PUBLIC_RSI_DEMO === '1') {
        const {demoHistory} = await import('@/lib/demo-platform');
        value = demoHistory(run);
      } else {
        const response = await fetch('/api/evolution?' + new URLSearchParams({run}),{cache:'no-store',signal});
        value = await response.json();
        if (!response.ok) throw new Error((value as unknown as {error:string}).error || 'Unable to load component lineage.');
      }
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
  const rounds = useMemo(() => data ? evolutionRounds(data).filter(round=>round.firstStep<=step) : [],[data,step]);
  const selectedRound = focusedRound === 0 || rounds.some(round=>round.round===focusedRound) ? focusedRound! : rounds.at(-1)?.round ?? 0;
  const linkedRound = hoveredRound ?? selectedRound;
  const page = useMemo(()=>data ? roundPage(data,selectedRound,step) : null,[data,selectedRound,step]);
  const summary = useMemo(() => data ? roundSummary(data,selectedRound,page?.step ?? step) : null,[data,selectedRound,page?.step,step]);
  const inspected = page?.snapshots.find(snapshot=>snapshot.id===inspectedId) || page?.defaultSnapshot;
  const bundle = inspected?.bundle;
  const version = data?.versions.find(v => v.id === selected);
  const component = data?.components.find(c => c.id === version?.component_id);
  const bundleId = version && bundle?.components[version.component_id] === version.id ? bundle.id : data?.bundles.findLast(b => b.step <= (page?.step ?? step) && b.components[version?.component_id || ''] === version?.id)?.id;
  const decision = data && version ? decisionAt(data,version.id,page?.step ?? step) || data.decisions.filter(d => d.scope === 'bundle' && d.version_id === bundleId && d.step <= (page?.step ?? step)).at(-1) : undefined;
  const choose = useCallback((id: string) => {evidenceTrigger.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;setSelected(id);setPanel(true);},[]);
  const focus = useCallback((round: number) => {
    const element=studioRoot.current?.closest<HTMLElement>('.console-main');
    if(element) preservedScroll.current={element,top:element.scrollTop};
    setFocusedRound(round);setInspectedId('');setSelected('');setHoveredRound(null);
  },[]);
  useLayoutEffect(()=>{
    const saved=preservedScroll.current;
    if(saved) {saved.element.scrollTop=saved.top;preservedScroll.current=null;}
  },[selectedRound]);
  const ready = data?.context?.initial_ready !== false;
  return <div ref={studioRoot} className={live ? "ce-root ce-console-embedded ce-follow-live" : "ce-root ce-console-embedded"}>
    <div className="ce-experiment">
      <div className="ce-controls ce-inspection-toolbar">
        <div className="ce-view-tabs" role="tablist" aria-label="Experiment charts">{(['lineage','evaluation'] as const).map((id,i) => <button key={id} role="tab" id={`chart-tab-${id}`} aria-selected={view === id} aria-controls={`chart-panel-${id}`} tabIndex={view === id ? 0 : -1} onClick={() => setView(id)} onKeyDown={event => {if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {event.preventDefault();const next=i === 0 ? 'evaluation' : 'lineage';setView(next);document.getElementById(`chart-tab-${next}`)?.focus();}}}>{id === 'lineage' ? 'Lineage' : 'Evaluation'}</button>)}</div>
        <div className="ce-snapshot-control"><Select value={inspected?.id || ''} disabled={!page?.snapshots.length} onValueChange={setInspectedId}>
          <SelectTrigger aria-label="Inspect round snapshot"><SelectValue placeholder="Not available yet"/></SelectTrigger><SelectContent>
            {page?.snapshots.map(snapshot=><SelectItem value={snapshot.id} key={snapshot.id}>{snapshot.label}</SelectItem>)}
          </SelectContent></Select></div>
        {page && <RoundPagination pages={page.pages} current={selectedRound} onRound={focus} disabled={!ready} position="top"/>}
        <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Legend and measurement notes"><MoreHorizontal size={17}/></Button></PopoverTrigger>
          <PopoverContent className="ce-record-popover ce-view-options" align="end">
            <div className="ce-options-legend"><span><i className="ce-key-normal"/>Version</span><span><i className="ce-key-rejected">×</i>Not retained</span><span><i className="ce-key-trunk"/>Derived version</span><span><i className="ce-key-carry"/>Unchanged version</span></div>
            <p>Results describe the retained TRAIN configuration. Candidate task subsets may differ. See the console summary for final TEST results.</p>
            <p>Metrics have independent axes. Missing values stay empty. Bundle selection does not establish individual component gains.</p>
          </PopoverContent>
        </Popover>
      </div>
      {error && <div className="ce-error" role="alert">{error}<Button variant="ghost" size="sm" onClick={() => void refresh()}>Retry</Button></div>}
      {!data ? <div className="ce-loading"><GitBranch size={22}/>{error ? 'Lineage unavailable' : 'Loading execution records…'}</div> : !ready ? <div className="ce-loading console-lineage-wait"><GitBranch size={28}/><strong>Waiting for the initial snapshot</strong><span>Lineage will appear when the worker freezes the actual starting Harness.</span></div> : <>
        {view === 'lineage' && summary && <section className="ce-round-summary" aria-label="Selected round summary">
          <div className="ce-round-summary-components">{summary.proposed.length ? summary.proposed.map(change=><button key={change.component.id} style={{color:COMPONENT_COLORS[(data.components.findIndex(c=>c.id===change.component.id)) % COMPONENT_COLORS.length]}} onClick={()=>choose(change.versions.at(-1)!.id)}><i/>{change.component.name}<small>{change.versions.at(-1)!.label}</small></button>) : <span>{summary.round ? 'No edits proposed' : `${data.components.length} components`}</span>}</div>
          <span className="ce-round-outcome">{summary.status}</span>
          {summary.round>0 && <Popover><PopoverTrigger asChild><Button variant="ghost" size="sm" aria-label="Round decision details">Details<ChevronDown size={13}/></Button></PopoverTrigger><PopoverContent className="ce-decision-details" align="end"><strong>Round {String(summary.round).padStart(2,'0')} decision</strong><p>{summary.reason || (summary.resolved ? 'No decision reason recorded.' : 'The selection decision has not been recorded yet.')}</p><small>{summary.retained ? `Selected ${summary.retained} · ${summary.retainedChanges} component changes` : 'Awaiting selection'}</small></PopoverContent></Popover>}
        </section>}
        <div className="ce-single-view" role="tabpanel" id={`chart-panel-${view}`} aria-labelledby={`chart-tab-${view}`}>
          {view === 'lineage' ? <section className="ce-lineages"><h2 className="sr-only">Component lineage</h2><div className="ce-tree-scroll"><ComponentTree data={data} step={step} selected={selected} configuration={bundle?.components} selectedRound={selectedRound} onSelect={choose}/></div></section> : <section className="ce-results"><h2 className="sr-only">Retained configuration results</h2><RoundOutcomeChart data={data} step={step} activeRound={linkedRound} onHoverRound={setHoveredRound} onRound={focus}/></section>}
        </div>
        {view === 'lineage' && page && <RoundPagination pages={page.pages} current={selectedRound} onRound={focus} position="bottom"/>}
        <div className="console-lineage-footnote"><span>TRAIN measurements · {rounds.length} recorded {rounds.length === 1 ? 'round' : 'rounds'}</span><span>{view === 'lineage' ? 'Click a version to inspect its snapshot' : 'TRAIN measurements for retained configurations'}</span></div>
      </>}
    </div>
    <Sheet open={panel && !!version} onOpenChange={setPanel}><SheetContent className="ce-evidence" onCloseAutoFocus={event=>{event.preventDefault();evidenceTrigger.current?.focus({preventScroll:true});}}><SheetHeader><SheetTitle>{component?.name} <code>{version?.label}</code></SheetTitle><SheetDescription>Recorded component snapshot and adoption evidence.</SheetDescription></SheetHeader>{version && data && <><div className="ce-version-meta"><span>{version.parent_id ? `Parent: ${data.versions.find(v => v.id === version.parent_id)?.label}` : 'Initial snapshot'}</span><span>Round {version.round}</span><span>{version.digest.slice(0,10)}</span></div><div className={`ce-verdict ${decision?.outcome || 'unknown'}`}><strong>{decision ? decisionLabels[decision.outcome] : version.step === 0 ? 'Initial version' : 'No adoption decision recorded'}</strong>{decision?.reason && <p>{decision.reason}</p>}{decision?.scope === 'bundle' && <small>Decision scope: complete Harness, not an independent component test.</small>}</div><div className="ce-evidence-scroll">{version.files.length ? version.files.map(file => <details key={file.path}><summary>{file.path}<ChevronDown size={12}/></summary><pre>{file.diff}</pre></details>) : <p>This component has no custom content in this snapshot.</p>}{decision?.evidence && <details><summary>Decision evidence<ChevronDown size={12}/></summary><p>{decision.evidence}</p></details>}</div></>}</SheetContent></Sheet>
  </div>;
}

function RoundPagination({pages,current,onRound,disabled=false,position}:{pages:number[];current:number;onRound:(round:number)=>void;disabled?:boolean;position:'top'|'bottom'}) {
  const index=pages.indexOf(current);
  return <nav className={`ce-round-pagination is-${position}`} aria-label={`${position==='top'?'Evolution':'Bottom'} round pagination`}>
    <Button variant="outline" size="icon-sm" aria-label="Previous round" disabled={disabled || index<=0} onClick={()=>onRound(pages[index-1])}><ChevronLeft size={16}/></Button>
    <span className="ce-page-label" aria-live="polite"><strong>{current ? `Round ${String(current).padStart(2,'0')}` : 'Baseline'}</strong></span>
    <Button variant="outline" size="icon-sm" aria-label="Next round" disabled={disabled || index<0 || index>=pages.length-1} onClick={()=>onRound(pages[index+1])}><ChevronRight size={16}/></Button>
  </nav>;
}
