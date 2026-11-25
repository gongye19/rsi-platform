"use client";
import {useEffect,useMemo,useRef,useState} from 'react';
import {FileJson, FileText, Loader2, Search, Terminal} from 'lucide-react';
import {Input} from '@/components/ui/input';
import {Button} from '@/components/ui/button';
import {platformRead,type Artifact,type Event} from '@/lib/console-types';
export function RunArtifacts({run, revision}: {run: string; revision: number}) {
  const [files,setFiles] = useState<Artifact[]>([]);
  const [query,setQuery] = useState('');
  const [kind,setKind] = useState('all');
  const [selected,setSelected] = useState('');
  const [content,setContent] = useState('');
  const [loading,setLoading] = useState(false);
  const [error,setError] = useState('');
  const pending = useRef<AbortController | null>(null);
  useEffect(() => {
    const abort = new AbortController();
    void platformRead<Artifact[]>('?' + new URLSearchParams({run,artifacts:'1'}),{signal:abort.signal}).then(setFiles).catch(e => {if (!abort.signal.aborted) setError((e as Error).message);});
    return () => abort.abort();
  },[run,revision]);
  const filtered = useMemo(() => files.filter(f => f.path.toLowerCase().includes(query.toLowerCase()) && (kind === 'all' || kind === 'traces' && /api_calls|trial\.jsonl|trace/i.test(f.path) || kind === 'answers' && /answer/i.test(f.path) || kind === 'results' && /result\.json|final\.json|rollout\//.test(f.path))),[files,query,kind]);
  useEffect(() => () => pending.current?.abort(), []);
  function open(file: Artifact) {
    pending.current?.abort();
    const abort = new AbortController(); pending.current = abort;
    setSelected(file.root+':'+file.path); setLoading(true);setError('');setContent('');
    void platformRead<{content: string}>('?' + new URLSearchParams({run,root:String(file.root),path:file.path}), {signal:abort.signal}).then(value => {if (!abort.signal.aborted) setContent(value.content);}).catch(e => {if (!abort.signal.aborted) setError((e as Error).message);}).finally(() => {if (!abort.signal.aborted) setLoading(false);});
  }
  return <div className="artifact-workspace"><aside className="artifact-list"><div className="artifact-search"><Search size={14}/><Input aria-label="Search artifacts" placeholder="Search artifacts…" value={query} onChange={e => setQuery(e.target.value)}/></div><div className="artifact-filters">{['all','traces','answers','results'].map(value => <button key={value} aria-pressed={kind === value} onClick={() => setKind(value)}>{value[0].toUpperCase()+value.slice(1)}</button>)}</div><p className="artifact-count">{filtered.length} files · server-side records</p><div className="artifact-files">{filtered.slice(0,300).map(file => <button key={file.root+':'+file.path} title={file.path} aria-pressed={selected === file.root+':'+file.path} onClick={() => open(file)}>{/api_calls|trial\.jsonl/.test(file.path) ? <Terminal size={14}/> : /\.json/.test(file.path) ? <FileJson size={14}/> : <FileText size={14}/>}<span>{file.path.split('/').at(-1)}<small>{file.path}</small></span></button>)}{filtered.length > 300 && <p className="artifact-count">Showing 300 matches. Search to narrow the list.</p>}{files.length === 0 && <p className="artifact-count">No artifacts have been written yet.</p>}</div></aside><section className="artifact-viewer" aria-label="Artifact contents">{error ? <div className="console-alert" role="alert">{error}</div> : loading ? <div className="console-empty"><Loader2 className="animate-spin"/>Loading artifact…</div> : selected ? <><div className="artifact-path">{selected.split(':').slice(1).join(':')}</div><pre>{content}</pre></> : <div className="console-empty"><FileText size={28}/><h3>Inspect run evidence</h3><p>Select a trace, answer, result or log from the list.</p></div>}</section></div>;
}
export function RunActivity({run,revision}: {run: string; revision: number}) {
  const [events,setEvents] = useState<Event[]>([]);
  const [error,setError] = useState('');
  const [more,setMore] = useState(false);
  const cursor = useRef(0);
  useEffect(() => {
    const abort = new AbortController();
    void platformRead<Event[]>('?' + new URLSearchParams({run,events:'1',after:String(cursor.current)}),{signal:abort.signal}).then(value => {if (abort.signal.aborted) return;setEvents(old => [...new Map([...old,...value].map(event => [event.seq,event])).values()].sort((a,b) => a.seq-b.seq));cursor.current=Math.max(cursor.current,value.at(-1)?.seq || 0);setMore(value.length === 500);setError('');}).catch(e => {if (!abort.signal.aborted) setError((e as Error).message);});
    return () => abort.abort();
  },[run,revision]);
  async function loadMore() {
    try {const value = await platformRead<Event[]>('?' + new URLSearchParams({run,events:'1',after:String(cursor.current)}));setEvents(old => [...new Map([...old,...value].map(event => [event.seq,event])).values()].sort((a,b) => a.seq-b.seq));cursor.current=Math.max(cursor.current,value.at(-1)?.seq || 0);setMore(value.length === 500);} catch(e) {setError((e as Error).message);}
  }
  return <section className="activity-panel"><h2>Run activity</h2><p>Persisted queue events and worker checkpoints.</p>{error && <div className="console-alert" role="alert">{error}</div>}<div className="activity-events">{events.map(event => <details key={event.seq}><summary><i/><strong>{event.kind.replaceAll('_',' ')}</strong><time>{new Date(event.at*1000).toLocaleString('en-GB')}</time><span>#{event.seq}</span></summary><pre>{JSON.stringify(event.payload,null,2)}</pre></details>)}</div>{events.length === 0 && <p>No events have been recorded yet.</p>}{more && <Button variant="outline" onClick={() => void loadMore()}>Load more events</Button>}</section>;
}
