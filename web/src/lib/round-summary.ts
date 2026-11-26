import {evolutionRounds,roundChanges} from './component-layout';
import type {ComponentHistory} from './component-types';
/** A round summary describes proposed edits and the selected tuple, not component test grades. */
export function roundSummary(data:ComponentHistory, number:number, step:number) {
  const round=evolutionRounds(data).find(row=>row.round===number && row.firstStep<=step);
  if (!round) return {round:0,proposed:[],retainedChanges:0,resolved:true,status:'Initial Harness',retained:data.bundles.find(bundle=>bundle.step===0)?.id,reason:''};
  const changes=roundChanges(data,round,step);
  const proposed=changes.filter(change=>change.generated.length).map(change=>({component:change.component,versions:change.generated}));
  const resolved=round.resolutionStep!=null && round.resolutionStep<=step && !!round.result;
  const retainedChanges=resolved ? changes.filter(change=>change.after && change.after!==change.before).length : 0;
  const decision=data.decisions.filter(d=>d.scope==='bundle' && d.step>=round.firstStep && d.step<=Math.min(step,round.lastStep)).findLast(d=>resolved && !retainedChanges ? d.outcome==='not_retained' || d.outcome==='failed' : d.outcome==='retained');
  return {round:number,proposed,retainedChanges,resolved,status:!resolved?'Decision pending':retainedChanges?'Updated Harness retained':'Parent retained',retained:resolved?round.result?.id:undefined,reason:decision?.reason || ''};
}
