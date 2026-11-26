import {test} from 'node:test';
import assert from 'node:assert/strict';
import example from '../../examples/component-history.example.json';
import type {ComponentHistory} from './component-types';
import {roundPageGraph} from './component-round-page';
import {lineageOutcome} from './lineage-outcome';
const data=example as unknown as ComponentHistory;

test('adoption icons follow the recorded complete Harness selection',()=>{
  const graph=roundPageGraph(data,2,9,1000);
  const prior=graph.nodes.find(node=>node.data.versionId==='subagent-v1' && node.data.stage==='test')!;
  const candidate=graph.nodes.find(node=>node.data.versionId==='subagent-v2' && node.data.stage==='test')!;
  assert.equal(lineageOutcome(prior.data,graph.page.round,graph.page.step)?.kind,'retained');
  assert.equal(lineageOutcome(candidate.data,graph.page.round,graph.page.step)?.kind,'rejected');
});
test('a passing component check does not claim adoption before the round is resolved',()=>{
  const graph=roundPageGraph(data,2,9,1000);
  const point=graph.nodes.find(node=>node.data.versionId==='subagent-v2' && node.data.stage==='test')!;
  assert.equal(lineageOutcome({...point.data,caption:'Passed',rejected:false},graph.page.round,5)?.kind,'pending');
  assert.equal(lineageOutcome({...point.data,caption:'Passed',rejected:false},graph.page.round,9)?.kind,'rejected');
});
test('starting and candidate creation points have no outcome icon',()=>{
  const graph=roundPageGraph(data,1,9,1000);
  assert(graph.nodes.some(node=>node.data.stage==='experiment'));
  for(const node of graph.nodes.filter(node=>node.data.stage!=='test'))
    assert.equal(lineageOutcome(node.data,graph.page.round,graph.page.step),null);
});
