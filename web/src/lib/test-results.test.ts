import {test} from 'node:test';
import assert from 'node:assert/strict';
import {testResults,testScore} from './test-results';

test('only actual held-out scores become evaluation points; missing TEST stays missing',()=>{
  assert.deepEqual(testResults({},'v0').map(point=>point.score),[null,null]);
  const results=testResults({initial:{metrics:{pass_at_1:0}},selected:{metrics:{primary_metric:'mean_reward',mean_reward:.8,pass_at_1:1}}},'v2');
  assert.deepEqual(results.map(point=>point.score),[0,.8]);
  assert.equal(results[1].version,'v2');
  assert.equal(testScore({pass_at_1:NaN}),null);
});
test('keeping the initial Harness can display its reused TEST result without inventing improvement',()=>{
  const results=testResults({initial:{metrics:{pass_at_1:.5}},selected:{metrics:{pass_at_1:.5},reused_initial:true}},'v0');
  assert.deepEqual(results.map(point=>point.score),[.5,.5]);
  assert.deepEqual(results.map(point=>point.version),['v0','v0']);
});
