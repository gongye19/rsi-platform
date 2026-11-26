import {test} from 'node:test';
import assert from 'node:assert/strict';
import example from '../../examples/component-history.example.json';
import type {ComponentHistory} from './component-types';
import {componentComparison,changedLines} from './component-comparison';
import {roundPageGraph} from './component-round-page';
const data=example as unknown as ComponentHistory;
test('a comparison uses the actual parent and includes added and removed files',()=>{
  const copy=structuredClone(data),after=copy.versions.find(v=>v.id==='subagent-v3')!;
  after.parent_id='subagent-v2';
  const parent=copy.versions.find(v=>v.id==='subagent-v2')!;
  parent.files=[{path:'old.md',change:'snapshot',diff:'old'},{path:'same.md',change:'snapshot',diff:'before'}];
  after.files=[{path:'new.md',change:'snapshot',diff:'new'},{path:'same.md',change:'snapshot',diff:'after'}];
  const comparison=componentComparison(copy,after.id)!;
  assert.equal(comparison.before.id,parent.id);
  assert.deepEqual(comparison.files.map(f=>f.status),['Added','Removed','Modified']);
  assert.equal(comparison.files[1].after,null);
  assert.equal(comparison.files[0].before,null);
});
test('changed text preserves exact whitespace and identical context',()=>{
  const lines=changedLines('same\nold\ntail','same\nnew\ntail');
  assert.deepEqual(lines.before.map(l=>l.changed),[false,true,false]);
  assert.deepEqual(lines.after.map(l=>l.changed),[false,true,false]);
});
test('a fork balances the retained parent and candidate around the start node',()=>{
  const graph=roundPageGraph(data,2,9,1100);
  const start=graph.nodes.find(n=>n.id==='subagent:boundary:1')!;
  const targets=graph.nodes.filter(n=>n.data.componentId==='subagent' && n.data.stage==='test');
  assert(targets.length>=2);
  const offsets=targets.map(n=>n.position.y-start.position.y);
  assert(offsets.some(n=>n<0) && offsets.some(n=>n>0));
  assert(Math.abs(offsets.reduce((a,b)=>a+b,0))<.01);
  assert.equal(graph.stages.at(-1)!.x,graph.width-26);
});
