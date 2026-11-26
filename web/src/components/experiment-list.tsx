"use client";
import {useState} from 'react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {stateLabels, type Run} from '@/lib/console-types';
export function RunStatus({state}: {state: string}) {return <span className={`run-status status-${state}`}><i/>{stateLabels[state] || state}</span>;}
export default function ExperimentList({runs,selected,loading,busy,onSelect,onNew}: {runs: Run[];selected: string;loading: boolean;busy: boolean;onSelect: (id: string) => void;onNew: () => void}) {
  const [search,setSearch] = useState('');
  const visible = runs.filter(run => `${run.id} ${run.configuration?.benchmark || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <aside className="experiment-list" aria-label="Experiments">
    <header><h2>Experiments <span>{runs.length}</span></h2><Button onClick={onNew} disabled={busy}>New experiment</Button></header>
    <div className="experiment-list-controls"><Input aria-label="Search experiments" placeholder="Search experiments…" value={search} onChange={e => setSearch(e.target.value)}/></div>
    <nav className="experiment-list-rows" aria-label="Experiment runs">
      {visible.map(run => <button key={run.id} className="experiment-list-row" aria-label={`Open ${run.id}`} aria-current={selected === run.id ? 'page' : undefined} title={`${run.id} · ${stateLabels[run.state] || run.state}`} onClick={() => onSelect(run.id)} disabled={busy}>
        <i className={`experiment-state-dot state-${run.state}`} aria-label={stateLabels[run.state] || run.state}/><strong>{run.id}</strong>
      </button>)}
      {!visible.length && <p className="experiment-list-empty">{loading ? 'Loading experiments…' : 'No matching experiments.'}</p>}
    </nav>
  </aside>;
}
