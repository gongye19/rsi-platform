import {componentGraph, type LineagePoint} from './component-graph';
import {evolutionRounds} from './component-layout';
import {activeAt, type ComponentHistory, type ConfigurationSnapshot} from './component-types';

/** A page is bounded by recorded events; later snapshots never enter an earlier round. */
export function roundPage(data:ComponentHistory, round:number, step:number) {
  const recorded=evolutionRounds(data).filter(row=>row.firstStep<=step);
  const current=recorded.find(row=>row.round===round);
  const end=current ? Math.min(step,current.lastStep) : 0;
  const snapshots:{id:string;label:string;bundle:ConfigurationSnapshot}[]=[];
  const add=(role:string,label:string,bundle?:ConfigurationSnapshot)=>{
    if(bundle && bundle.step<=end) snapshots.push({id:`${role}:${bundle.id}`,label:`${label} · ${bundle.id}`,bundle});
  };
  if(current) {
    add('start','Start',current.start);
    for(const bundle of data.bundles.filter(row=>row.round===round && row.step>=current.firstStep && row.step<=end && row.id!==current.result?.id))
      add('candidate','Candidate',bundle);
    if(current.resolutionStep!=null && current.resolutionStep<=end) add('result','Selected',current.result);
  } else add('initial','Initial',activeAt(data,0));
  return {round:current,step:end,pages:[0,...recorded.map(row=>row.round)],snapshots,
    defaultSnapshot:snapshots.findLast(row=>row.id.startsWith('result:')) || snapshots.findLast(row=>row.id.startsWith('candidate:')) || snapshots[0]};
}

/** Keep one round's occurrences, plus explicit earlier parents required by its edges. */
export function roundPageGraph(data:ComponentHistory, round:number, step:number, width:number) {
  const page=roundPage(data,round,step);
  const full=componentGraph(data,page.step,undefined,false,true);
  const ri=full.layout.rounds.findIndex(row=>row.round===round);
  const edges=ri<0 ? [] : full.edges.filter(edge=>edge.data?.round===round && edge.data.kind!=='retained');
  const ids=new Set<string>();
  for(const component of data.components) {
    ids.add(`${component.id}:boundary:${Math.max(0,ri)}`);
  }
  for(const node of full.nodes) if(node.data.round===round && node.data.stage!=='input') ids.add(node.id);
  const localIds=new Set(ids);
  for(const edge of edges) {ids.add(edge.source);ids.add(edge.target);}
  const byId=new Map(full.nodes.map(node=>[node.id,node]));
  const extra=new Map<string,LineagePoint[]>();
  const aliases=new Map<string,string>();
  for(const id of ids) {
    const node=byId.get(id);
    if(node && !localIds.has(id)) {
      const references=extra.get(node.data.componentId)||[];
      const same=references.find(reference=>reference.data.versionId===node.data.versionId);
      if(same) {aliases.set(id,same.id);ids.delete(id);}
      else extra.set(node.data.componentId,[...references,node]);
    }
  }
  // Consistent lane sizes keep the page stationary when moving between rounds.
  const versions=new Map(data.versions.map(version=>[version.id,version]));
  const maxReferences=Math.max(0,...full.layout.rounds.flatMap(record=>data.components.map(component=>{
    const before=record.start?.components[component.id] || component.baseline_version_id;
    const parents=data.versions.filter(version=>version.round===record.round && version.component_id===component.id && version.parent_id && version.parent_id!==before && versions.get(version.parent_id)?.round!==record.round).map(version=>version.parent_id);
    const after=record.result?.components[component.id];
    if(after && after!==before && versions.get(after)?.round!==record.round) parents.push(after);
    return new Set(parents).size;
  })));
  const radius=Math.max(16,...[...full.layout.positions].map(([id,position])=>{
    const version=versions.get(id)!;
    return Math.abs(position.y-full.layout.rows.get(version.component_id)!.center);
  }));
  const center=36+radius;
  const laneHeight=Math.max(80,center+radius+12,center+maxReferences*22+14);
  const graphWidth=Math.max(820,width);
  const left=40,right=graphWidth-220;
  const sourceLeft=full.layout.inputX(Math.max(0,ri)),sourceRight=full.layout.testX(Math.max(0,ri));
  const x=(value:number)=>left+(value-sourceLeft)/(sourceRight-sourceLeft)*(right-left);
  const rows=new Map(data.components.map((component,index)=>[component.id,{top:8+index*(laneHeight+8),height:laneHeight,center:8+index*(laneHeight+8)+center}]));
  const nodes=[...ids].flatMap(id=>{
    const node=byId.get(id);
    if(!node)return [];
    const row=rows.get(node.data.componentId)!;
    const originalRow=full.layout.rows.get(node.data.componentId)!;
    const start=id===`${node.data.componentId}:boundary:${Math.max(0,ri)}`;
    const references=extra.get(node.data.componentId)||[];
    const referenceIndex=references.findIndex(item=>item.id===id);
    return [{...node,position:{x:start || referenceIndex>=0 ? left : x(node.position.x),
      y:row.center+(referenceIndex>=0 ? (referenceIndex+1)*22 : start ? 0 : node.position.y-originalRow.center)},
      data:{...node.data,round,root:start,contextName:true,arrival:false,
        caption:referenceIndex>=0 ? `Earlier · R${node.data.round}` : node.data.caption}}];
  });
  return {nodes,edges:edges.map(edge=>({...edge,source:aliases.get(edge.source)||edge.source,target:aliases.get(edge.target)||edge.target,data:edge.data?{...edge.data,arrival:false}:edge.data})),rows,
    width:graphWidth,height:8+data.components.length*(laneHeight+8),
    stages:ri<0 ? [{label:'Initial',x:left}] : [
      {label:'Start',x:left},{label:'Candidate',x:x(full.layout.candidateX(ri))},
      {label:'Evaluation',x:x(full.layout.testX(ri))}],page};
}
