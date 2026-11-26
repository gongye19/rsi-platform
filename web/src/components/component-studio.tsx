"use client";
import {useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState} from 'react';
import {Check, X, ChevronLeft, ChevronRight, GitBranch, MoreHorizontal} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Popover, PopoverContent, PopoverTrigger} from '@/components/ui/popover';
import ComponentTree from './component-tree';
import RoundOutcomeChart from './round-outcome-chart';
import {evolutionRounds} from '@/lib/component-layout';
import {type ComponentHistory} from '@/lib/component-types';
import {componentLabels} from '@/lib/console-types';
import './component-studio.css';
export default function ComponentStudio({run, live, revision}: {run: string; live: boolean; revision: number}) {
  const studioRoot = useRef<HTMLDivElement>(null);
  const preservedScroll = useRef<{element:HTMLElement;top:number} | null>(null);
  const [view,setView] = useState<'lineage' | 'evaluation'>('lineage');
  const [data,setData] = useState<ComponentHistory | null>(null);
  const [error,setError] = useState('');
  const [selected,setSelected] = useState('');
  const [hoveredRound,setHoveredRound] = useState<number | null>(null);
  const [focusedRound,setFocusedRound] = useState<number | null>(null);
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
  const choose = useCallback((id:string)=>setSelected(id),[]);
  const focus = useCallback((round: number) => {
    const element=studioRoot.current?.closest<HTMLElement>('.console-main');
    if(element) preservedScroll.current={element,top:element.scrollTop};
    setFocusedRound(round);setSelected('');setHoveredRound(null);
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
      </div>
      {error && <div className="ce-error" role="alert">{error}<Button variant="ghost" size="sm" onClick={() => void refresh()}>Retry</Button></div>}
      {!data ? <div className="ce-loading"><GitBranch size={22}/>{error ? 'Lineage unavailable' : 'Loading execution records…'}</div> : !ready ? <div className="ce-loading console-lineage-wait"><GitBranch size={28}/><strong>Waiting for the initial snapshot</strong><span>Lineage will appear when the worker freezes the actual starting Harness.</span></div> : <>
        <div className="ce-single-view" role="tabpanel" id={`chart-panel-${view}`} aria-labelledby={`chart-tab-${view}`}>
          {view === 'lineage' ? <section className="ce-lineages">
            <h2 className="sr-only">Component lineage</h2>
            <div className="ce-lineage-toolbar">
              <RoundPagination pages={[0,...rounds.map(round=>round.round)]} current={selectedRound} onRound={focus} disabled={!ready} position="top"/>
        <Popover><PopoverTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="Legend and measurement notes"><MoreHorizontal size={17}/></Button></PopoverTrigger>
          <PopoverContent className="ce-record-popover ce-view-options" align="end">
            <div className="ce-options-legend"><span><i className="ce-key-normal"/>Version</span><span><i className="ce-key-outcome"><Check size={10}/></i>Retained in Harness</span><span><i className="ce-key-outcome"><X size={10}/></i>Not retained</span><span><i className="ce-key-trunk"/>Derived version</span><span><i className="ce-key-carry"/>Unchanged version</span></div>
            <p>Results describe the retained TRAIN configuration. Candidate task subsets may differ. See the console summary for final TEST results.</p>
            <p>Metrics have independent axes. Missing values stay empty. Bundle selection does not establish individual component gains.</p>
          </PopoverContent>
        </Popover>
            </div>
            <div className="ce-tree-scroll"><ComponentTree data={data} step={step} selected={selected} selectedRound={selectedRound} onSelect={choose}/></div></section> : <section className="ce-results"><h2 className="sr-only">Retained configuration results</h2><RoundOutcomeChart data={data} step={step} activeRound={linkedRound} onHoverRound={setHoveredRound} onRound={focus}/></section>}
        </div>
        {view === 'lineage' && <RoundPagination pages={[0,...rounds.map(round=>round.round)]} current={selectedRound} onRound={focus} position="bottom"/>}
        {view === 'evaluation' && <div className="console-lineage-footnote"><span>TRAIN measurements · {rounds.length} recorded {rounds.length === 1 ? 'round' : 'rounds'}</span><span>TRAIN measurements for retained configurations</span></div>}
      </>}
    </div>

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
