import type {Metrics, Run} from './console-types';

export function testScore(metrics?:Metrics):number|null {
  const value=metrics?.primary_metric==='mean_reward'?metrics.mean_reward:metrics?.pass_at_1;
  return typeof value==='number' && Number.isFinite(value)?value:null;
}

/** Only held-out evaluations supplied by the service, never TRAIN subset scores. */
export function testResults(tests:Run['tests'],selectedVersion?:string) {
  return [
    {stage:'Baseline',version:'v0',score:testScore(tests.initial?.metrics)},
    {stage:'Final',version:selectedVersion || '',score:testScore(tests.selected?.metrics)},
  ];
}
