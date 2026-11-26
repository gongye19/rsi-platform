'use client';
import {useEffect,useMemo,useRef,useState,type CSSProperties} from 'react';
import {ChevronDown,ChevronRight} from 'lucide-react';
import {roundPageGraph} from '@/lib/component-round-page';
import {roundChanges} from '@/lib/component-layout';
import {COMPONENT_COLORS,type ComponentHistory} from '@/lib/component-types';
import ComponentComparison from './component-comparison';

type Props={data:ComponentHistory;step:number;selected:string;onSelect:(id:string)=>void;configuration?:Record<string,string>;selectedRound:number};
export default function ComponentTree({data,step,selected,onSelect,configuration,selectedRound}:Props) {
  const host=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(820);
  useEffect(()=>{
    if(!host.current)return;
    const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));
    observer.observe(host.current);
    return ()=>observer.disconnect();
  },[]);
  const graph=useMemo(()=>roundPageGraph(data,selectedRound,step,width),[data,selectedRound,step,width]);
  const changes=graph.page.round?roundChanges(data,graph.page.round,graph.page.step):[];
  const changed=new Set(changes.filter(change=>change.generated.length || (change.after && change.before!==change.after)).map(change=>change.component.id));
  const byId=new Map(graph.nodes.map(node=>[node.id,node]));
  function componentCard(component:ComponentHistory['components'][number]) {
    const index=data.components.findIndex(row=>row.id===component.id);
    const color=COMPONENT_COLORS[index%COMPONENT_COLORS.length];
    const row=graph.rows.get(component.id)!;
    const nodes=graph.nodes.filter(node=>node.data.componentId===component.id);
    const edges=graph.edges.filter(edge=>byId.get(edge.source)?.data.componentId===component.id);
    const change=changes.find(change=>change.component.id===component.id);
    const fallback=change?.generated.at(-1)?.id || configuration?.[component.id] || component.baseline_version_id;
    const open=data.versions.find(version=>version.id===selected)?.component_id===component.id;
    const diagramHeight=row.height-30;
    const y=(value:number)=>value-row.top-30;
    return <article key={component.id} className={`ce-component-card ${changed.has(component.id)?'has-changes':''}`} style={{'--component-color':color} as CSSProperties}>
      <button className="ce-component-toggle" aria-expanded={open} aria-controls={`comparison-${component.id}`} aria-label={`Compare ${component.name}`} onClick={()=>onSelect(open?'':fallback)}>{open?<ChevronDown size={15}/>:<ChevronRight size={15}/>}<i/>{component.name}</button>
      <div className="ce-component-diagram" style={{width:graph.width,height:diagramHeight}} role="group" aria-label={`${component.name} version lineage`}>
        <svg width={graph.width} height={diagramHeight} aria-hidden="true">{edges.map(edge=>{
          const a=byId.get(edge.source)!,b=byId.get(edge.target)!;
          const sourceY=y(a.position.y),targetY=y(b.position.y),middle=(a.position.x+b.position.x)/2;
          return <path key={edge.id} data-connection={edge.data?.kind} d={`M ${a.position.x} ${sourceY} C ${middle} ${sourceY}, ${middle} ${targetY}, ${b.position.x} ${targetY}`} stroke={color} strokeWidth={1.8} fill="none" strokeOpacity={edge.data?.kind==='held'?.45:.8} strokeDasharray={edge.data?.kind==='held'?'3 5':undefined}/>;
        })}</svg>
        {nodes.map(node=><button key={node.id} className={`ce-version ce-card-version ${selected===node.data.versionId?'is-inspected':''} ${configuration?.[component.id]===node.data.versionId?'is-member':''}`} style={{left:node.position.x,top:y(node.position.y),'--point-color':color} as CSSProperties} data-version-id={node.data.versionId} data-graph-round={selectedRound} data-node-final={node.data.stage==='test'} data-node-variant={node.data.rejected?'rejected':'normal'} aria-label={`Inspect ${component.name} ${node.data.label}, ${node.data.caption || (node.data.stage==='experiment'?'Candidate':'Start')}`} onClick={()=>onSelect(node.data.versionId)}><span className="ce-node-glyph">{node.data.rejected?'×':''}</span><span className="ce-version-label">{node.data.label}<small>{node.data.caption==='Unchanged'?'':node.data.caption==='Parent retained'?'Retained':node.data.caption}</small></span></button>)}
      </div>
      {open && <div id={`comparison-${component.id}`}><ComponentComparison key={selected} data={data} versionId={selected} step={graph.page.step}/></div>}
    </article>;
  }
  const primary=data.components.filter(component=>!selectedRound || changed.has(component.id));
  const unchanged=data.components.filter(component=>selectedRound && !changed.has(component.id));
  return <div ref={host} className="ce-round-canvas-scroll" role="region" aria-label={`Component lineage for ${selectedRound?`round ${selectedRound}`:'baseline'}`}>
    <div className="ce-page-stages" style={{width:graph.width}} aria-hidden="true">{graph.stages.map((stage,index)=><span key={stage.label} style={{left:stage.x,transform:index===graph.stages.length-1 && index>0?'translateX(-100%)':undefined}}>{stage.label}</span>)}</div>
    <div className="ce-component-cards" style={{minWidth:graph.width}} data-linked-round={selectedRound}>
      {primary.length?primary.map(componentCard):<p className="ce-no-changes">No component edits recorded in this round.</p>}
      {unchanged.length>0 && <details className="ce-unchanged-components" key={`unchanged-${selectedRound}`}><summary>Unchanged components <span>{unchanged.length}</span></summary>{unchanged.map(componentCard)}</details>}
    </div>
  </div>;
}
