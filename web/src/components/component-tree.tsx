'use client';
import {useEffect,useMemo,useRef,useState,type CSSProperties} from 'react';
import {Check,X} from 'lucide-react';
import {roundPageGraph} from '@/lib/component-round-page';
import {roundChanges} from '@/lib/component-layout';
import {lineageBranchPath} from '@/lib/lineage-branch';
import {lineageOutcome} from '@/lib/lineage-outcome';
import {COMPONENT_COLORS,type ComponentHistory} from '@/lib/component-types';
import ComponentComparison from './component-comparison';

type Props={data:ComponentHistory;step:number;selected:string;onSelect:(id:string)=>void;selectedRound:number};
const nameWidth=210;
export default function ComponentTree({data,step,selected,onSelect,selectedRound}:Props) {
  const host=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(1030);
  useEffect(()=>{
    if(!host.current)return;
    const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));
    observer.observe(host.current);
    return ()=>observer.disconnect();
  },[]);
  const graph=useMemo(()=>roundPageGraph(data,selectedRound,step,width-nameWidth),[data,selectedRound,step,width]);
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
    const fallback=change?.generated.at(-1)?.id || change?.after || change?.before || component.baseline_version_id;
    const open=data.versions.find(version=>version.id===selected)?.component_id===component.id;
    const diagramHeight=row.height;
    const y=(value:number)=>value-row.center+diagramHeight/2;
    return <article key={component.id} className="ce-component-card" style={{'--component-color':color} as CSSProperties}>
      <button className="ce-component-row" aria-expanded={open} aria-controls={`comparison-${component.id}`} aria-label={`Compare ${component.name}`} aria-describedby={`outcomes-${component.id}`} onClick={()=>onSelect(open?'':fallback)} style={{gridTemplateColumns:`${nameWidth}px ${graph.width}px`}}>
        <span className="ce-component-name-cell">{component.name}</span>
        <span className="ce-component-diagram" style={{width:graph.width,height:diagramHeight}} aria-hidden="true">
          <svg width={graph.width} height={diagramHeight}>{edges.map(edge=>{
            const a=byId.get(edge.source)!,b=byId.get(edge.target)!;
            const nearest=Math.min(...edges.filter(other=>other.source===edge.source).map(other=>byId.get(other.target)!.position.x));
            return <path key={edge.id} data-connection={edge.data?.kind} data-parent={edge.data?.parentId} d={lineageBranchPath({x:a.position.x,y:y(a.position.y)},{x:b.position.x,y:y(b.position.y)},nearest)} stroke={color} strokeWidth={1.8} fill="none" strokeOpacity={edge.data?.kind==='held'?.45:.8} strokeDasharray={edge.data?.kind==='held'?'3 5':undefined}/>;
          })}</svg>
          {nodes.map(node=>{
            const outcome=lineageOutcome(node.data,graph.page.round,graph.page.step);
            return <span key={node.id} className={`ce-version ce-card-version ${selected===node.data.versionId?'is-inspected':''}`} style={{left:node.position.x,top:y(node.position.y),'--point-color':color} as CSSProperties} data-version-id={node.data.versionId} data-graph-round={selectedRound} data-outcome={outcome?.kind} title={outcome?`${node.data.label} · ${outcome.label}`:node.data.label}>
              {outcome?<span className={`ce-outcome-glyph is-${outcome.kind}`}>{outcome.kind==='retained'?<Check size={11} strokeWidth={2}/>:outcome.kind==='rejected'?<X size={11} strokeWidth={2}/>:null}</span>:<span className="ce-node-glyph"/>}
              {!outcome && <span className="ce-version-label">{node.data.label}</span>}
            </span>;
          })}
        </span>
      </button>
      <span className="sr-only" id={`outcomes-${component.id}`}>{nodes.flatMap(node=>{const outcome=lineageOutcome(node.data,graph.page.round,graph.page.step);return outcome?[`${node.data.label}: ${outcome.label}`]:[];}).join('. ')}</span>
      <div id={`comparison-${component.id}`} hidden={!open}>{open && <ComponentComparison key={selected} data={data} versionId={selected} step={graph.page.step}/>}</div>
    </article>;
  }
  const primary=data.components.filter(component=>!selectedRound || changed.has(component.id));
  const unchanged=data.components.filter(component=>selectedRound && !changed.has(component.id));
  return <div ref={host} className="ce-round-canvas-scroll" role="region" aria-label={`Component lineage for ${selectedRound?`round ${selectedRound}`:'baseline'}`}>
    <div className="ce-page-stages" style={{width:nameWidth+graph.width}} aria-hidden="true">{graph.stages.map((stage,index)=><span key={stage.label} style={{left:nameWidth+stage.x,transform:index===graph.stages.length-1 && index>0?'translateX(-100%)':undefined}}>{stage.label}</span>)}</div>
    <div className="ce-component-cards" style={{minWidth:nameWidth+graph.width}} data-linked-round={selectedRound}>
      {primary.length?primary.map(componentCard):<p className="ce-no-changes">No component edits recorded in this round.</p>}
      {unchanged.length>0 && <details className="ce-unchanged-components" key={`unchanged-${selectedRound}`}><summary>Unchanged components <span>{unchanged.length}</span></summary>{unchanged.map(componentCard)}</details>}
    </div>
  </div>;
}
