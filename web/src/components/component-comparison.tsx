'use client';
import {changedLines,componentComparison} from '@/lib/component-comparison';
import {decisionAt,decisionLabels,type ComponentHistory} from '@/lib/component-types';

export default function ComponentComparison({data,versionId,step}:{data:ComponentHistory;versionId:string;step:number}) {
  const comparison=componentComparison(data,versionId);
  if(!comparison)return null;
  const {before,after,files}=comparison;
  const bundle=data.bundles.find(row=>row.step<=step && row.components[after.component_id]===after.id && row.step>=after.step);
  const decision=decisionAt(data,after.id,step) || (after.parent_id && data.decisions.findLast(row=>row.step<=step && row.scope==='bundle' && row.version_id===bundle?.id)) || undefined;
  return <section className="ce-inline-comparison" aria-label="Component content comparison">
    <div className="ce-comparison-meta"><strong>{before.id===after.id ? `Snapshot · ${after.label}` : `${before.label} → ${after.label}`}</strong>{decision && <span>{decisionLabels[decision.outcome]}</span>}</div>
    {!files.length && <p className="ce-comparison-empty">No custom files in this snapshot.</p>}
    {files.map((file,index)=>{
      const lines=changedLines(file.before,file.after);
      return <details className="ce-comparison-file" key={file.path} open={index===0}>
        <summary><span>{file.path}</span><small>{file.status}</small></summary>
        <div className={`ce-comparison-columns ${before.id===after.id?'is-single':''}`}>
          {before.id!==after.id && <div><h4>Before <span>{before.label}</span></h4><CodeSide lines={lines.before} missing={file.before===null} kind="removed"/></div>}
          <div><h4>{file.recordedPatch?'Recorded change':before.id===after.id?'Content':'After'} <span>{after.label}</span></h4><CodeSide lines={lines.after} missing={file.after===null} kind="added"/></div>
        </div>
      </details>;
    })}
    {decision?.reason && <details className="ce-comparison-decision"><summary>Decision evidence</summary><p>{decision.reason}</p>{decision.evidence && <small>{decision.evidence}</small>}{decision.scope==='bundle' && <small>Decision applies to the complete Harness.</small>}</details>}
  </section>;
}
function CodeSide({lines,missing,kind}:{lines:{text:string;changed:boolean}[];missing:boolean;kind:string}) {
  if(missing)return <p className="ce-comparison-empty">No file in this version.</p>;
  return <pre><code>{lines.map((line,index)=><span key={index} data-line={index+1} className={line.changed?`is-${kind}`:''}>{line.text || ' '}</span>)}</code></pre>;
}
