"use client";
import {useState} from 'react';
import {Trash2} from 'lucide-react';
import {Popover,PopoverContent,PopoverTrigger} from '@/components/ui/popover';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {stateLabels, type Run} from '@/lib/console-types';
export function RunStatus({state}: {state: string}) {return <span className={`run-status status-${state}`}><i/>{stateLabels[state] || state}</span>;}
export default function ExperimentList({runs,selected,loading,busy,onSelect,onNew,onDelete}: {runs: Run[];selected: string;loading: boolean;busy: boolean;onSelect: (id: string) => void;onNew: () => void;onDelete: (id:string) => Promise<boolean>}) {
  const [search,setSearch] = useState('');
  const visible = runs.filter(run => `${run.id} ${run.configuration?.benchmark || ''}`.toLowerCase().includes(search.toLowerCase()));
  return <aside className="experiment-list" aria-label="Experiments">
    <header><h2>Experiments <span>{runs.length}</span></h2><Button onClick={onNew} disabled={busy}>New experiment</Button></header>
    <div className="experiment-list-controls"><Input aria-label="Search experiments" placeholder="Search experiments…" value={search} onChange={e => setSearch(e.target.value)}/></div>
    <nav className="experiment-list-rows" aria-label="Experiment runs">
      {visible.map(run => <ExperimentRow key={run.id} run={run} selected={selected === run.id} busy={busy} onSelect={onSelect} onDelete={onDelete}/>)}
      {!visible.length && <p className="experiment-list-empty">{loading ? 'Loading experiments…' : 'No matching experiments.'}</p>}
    </nav>
  </aside>;
}

function ExperimentRow({run,selected,busy,onSelect,onDelete}: {run:Run;selected:boolean;busy:boolean;onSelect:(id:string)=>void;onDelete:(id:string)=>Promise<boolean>}) {
  const [open,setOpen] = useState(false);
  const active = ['queued','running','stopping'].includes(run.state);
  return <div className="experiment-list-entry" data-selected={selected}>
    <button className="experiment-list-row" aria-label={`Open ${run.id}`} aria-current={selected ? 'page' : undefined} title={`${run.id} · ${stateLabels[run.state] || run.state}`} onClick={() => onSelect(run.id)} disabled={busy}>
      <i className={`experiment-state-dot state-${run.state}`} aria-label={stateLabels[run.state] || run.state}/><strong>{run.id}</strong>
    </button>
    <Popover open={open} onOpenChange={value => {if (!busy) setOpen(value);}}><PopoverTrigger asChild><Button variant="ghost" size="icon-xs" className="experiment-delete-trigger" aria-label={`Delete ${run.id}`} title={active ? 'Stop the experiment before deleting it' : 'Delete experiment'} disabled={busy || active}><Trash2 size={13}/></Button></PopoverTrigger>
      <PopoverContent side="right" align="start" className="experiment-delete-confirm"><h3>Delete experiment?</h3><p>Are you sure you want to delete this experiment?</p><div><Button variant="outline" size="sm" disabled={busy} onClick={() => setOpen(false)}>Cancel</Button><Button variant="destructive" size="sm" disabled={busy} onClick={async () => {if (await onDelete(run.id)) setOpen(false);}}>Delete</Button></div></PopoverContent>
    </Popover>
  </div>;
}
