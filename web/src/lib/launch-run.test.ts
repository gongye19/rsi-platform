import {test} from 'node:test';
import assert from 'node:assert/strict';
import {launchRun} from './launch-run';
import type {Settings} from './console-types';
const settings: Settings = {models:{execution:'connection:executor',analysis:'other:analyst'},components:{allowed:['skills'],denied:['commands'],experimental_fields:[]},parameters:{HAI_TOTAL_CREATION_BUDGET:80},initial_harness:'',full_evaluation:true};
const input = {profile:'benchmark.toml',run_id:'one',settings,start:true};
test('Start run saves the chosen settings before queueing that exact run',async () => {
  const calls: unknown[] = [];
  await launchRun(input,async () => {calls.push('persisted');},async body => {calls.push(body);});
  assert.deepEqual(calls,[{action:'create',profile:'benchmark.toml',run_id:'one',settings},'persisted',{action:'start',run_id:'one'}]);
});
test('a creation failure never starts a model job or retries creation',async () => {
  let calls=0;let persisted=false;
  await assert.rejects(launchRun(input,async () => {persisted=true;},async () => {calls++;throw new Error('offline');}),/offline/);
  assert.equal(calls,1);assert.equal(persisted,false);
});
test('a start failure preserves the saved run so the console can identify its draft',async () => {
  let calls=0;let persisted=false;
  await assert.rejects(launchRun(input,async () => {persisted=true;},async body => {calls++;if (body.action==='start') throw new Error('not ready');}),/not ready/);
  assert.equal(calls,2);assert.equal(persisted,true);
});
test('saving a draft never queues execution',async () => {
  const calls: unknown[] = [];
  await launchRun({...input,start:false},async () => {},async body => {calls.push(body);});
  assert.equal(calls.length,1);
});
