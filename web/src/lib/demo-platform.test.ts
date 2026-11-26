import {test} from 'node:test';
import assert from 'node:assert/strict';
import {buildDemoHistory,demoRequest,materializeDemoRun,seedDemoStore} from './demo-platform';
import {roundSummary} from './round-summary';
import {combinedRoundResults} from './round-results';
import type {Run,Settings} from './console-types';

test('synthetic history preserves rejection, retained measurements and 16 components',()=>{
 const store=seedDemoStore(10000),run=materializeDemoRun(store,store.runs[0],10000);
 const history=buildDemoHistory(run);
 assert.equal(history.source,'example');assert.equal(history.components.length,16);
 assert.equal(run.state,'succeeded');assert.equal(run.selected_version,'candidate-03');
 assert.equal(roundSummary(history,2,9).status,'Parent retained');
 assert.equal(roundSummary(history,3,9).retainedChanges,2);
 assert.deepEqual(combinedRoundResults(history,9).map(p=>p.score),[9/13,11/13,11/13,12/13]);
});
test('simulation respects editable components, budget and pending outcomes',()=>{
 const store=seedDemoStore(10000),run=store.runs[0];
 run.configuration.components={allowed:['skills'],denied:[],experimental_fields:[]};
 const history=buildDemoHistory(run,2);
 assert(history.versions.filter(v=>v.parent_id).every(v=>v.component_id==='skills'));
 assert.equal(history.decisions.length,0);
 run.configuration.components.allowed=[];
 assert.equal(buildDemoHistory(run).steps.length,1);
 run.configuration.components.allowed=['skills'];
 run.configuration.parameters!.HAI_TOTAL_CREATION_BUDGET=13;
 assert.equal(buildDemoHistory(run).steps.length,1);
});
test('browser-local lifecycle never invokes fetch and deletion stays deleted',async()=>{
 const original=globalThis.fetch;let networkCalls=0;
 globalThis.fetch=(()=>{networkCalls++;throw new Error('Unexpected network');}) as typeof fetch;
 try {
  const settings:Settings={models:{execution:'open-model',analysis:'gpt-analysis'},benchmark:'data-analysis',components:{allowed:['skills'],denied:[],experimental_fields:[],proposal_only:['diagnostic']},parameters:{HAI_TOTAL_CREATION_BUDGET:52},initial_harness:'',full_evaluation:false};
  const send=(body:unknown)=>demoRequest('',{method:'POST',body:JSON.stringify(body)});
  await send({action:'create',run_id:'mock-lifecycle',settings});
  await send({action:'start',run_id:'mock-lifecycle'});
  let run=await demoRequest<Run>('?run=mock-lifecycle');
  assert.equal(run.state,'running');assert.equal(run.configuration.benchmark,'data-analysis');assert.deepEqual(run.configuration.components?.proposal_only,['diagnostic']);
  assert.equal(run.configuration.models?.execution?.model,'open-model');
  await send({action:'stop',run_id:run.id});
  run=await demoRequest<Run>('?run=mock-lifecycle');assert.equal(run.state,'stopped');
  await send({action:'delete',run_id:run.id});
  assert(!(await demoRequest<Run[]>()).some(row=>row.id==='mock-lifecycle'));
  await assert.rejects(demoRequest('?run=mock-lifecycle'));
  assert.equal(networkCalls,0);
 } finally {globalThis.fetch=original;}
});

test('public demo server rejects private service access before fetch',async()=>{
 const {platform}=await import('./platform');
 const previous=process.env.NEXT_PUBLIC_RSI_DEMO;
 const original=globalThis.fetch;let calls=0;
 process.env.NEXT_PUBLIC_RSI_DEMO='1';
 globalThis.fetch=(()=>{calls++;throw new Error('Private service must not be called');}) as typeof fetch;
 try {
  const response=await platform('/v1/runs');
  assert.equal(response.status,503);assert.equal(calls,0);
 } finally {
  globalThis.fetch=original;
  if(previous==null)delete process.env.NEXT_PUBLIC_RSI_DEMO;else process.env.NEXT_PUBLIC_RSI_DEMO=previous;
 }
});
