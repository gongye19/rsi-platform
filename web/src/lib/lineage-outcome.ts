import type {PointData} from './component-graph';
import type {EvolutionRound} from './component-layout';
/** Adoption comes from the recorded selected tuple, never from a passing check alone. */
export function lineageOutcome(point:PointData,round:EvolutionRound|undefined,step:number) {
  if(point.stage!=='test')return null;
  const resolved=round?.resolutionStep!=null && round.resolutionStep<=step;
  if(resolved && round.result?.components[point.componentId]===point.versionId)
    return {kind:'retained' as const,label:'Retained in selected Harness'};
  if(point.rejected || (resolved && round.result?.components[point.componentId]))return {kind:'rejected' as const,label:point.caption==='Failed'?'Component check failed':'Not retained'};
  return {kind:'pending' as const,label:'Evaluated; selection pending'};
}
