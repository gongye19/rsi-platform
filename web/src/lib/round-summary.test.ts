import {test} from 'node:test';
import assert from 'node:assert/strict';
import example from '../../examples/component-history.example.json';
import type {ComponentHistory} from './component-types';
import {roundSummary} from './round-summary';
const data=example as unknown as ComponentHistory;
test('a round before selection never claims retained changes',()=>{
 const summary=roundSummary(data,2,5);
 assert.equal(summary.resolved,false);
 assert.equal(summary.retained,undefined);
 assert.equal(summary.status,'Decision pending');
 assert(summary.proposed.length>0);
 assert(summary.proposed.every(change=>change.versions.every(version=>version.step<=5)));
});
test('parent retention compares the actual selected component tuple',()=>{
 const copy=structuredClone(data);
 copy.steps[6].active_bundle_id='accepted-r1';
 const summary=roundSummary(copy,2,9);
 assert.equal(summary.resolved,true);
 assert.equal(summary.status,'Parent retained');
 assert.equal(summary.retainedChanges,0);
 assert.equal(summary.retained,'accepted-r1');
 assert(summary.proposed.length>0);
});
test('accepted edits are counted as tuple changes rather than test passes',()=>{
 const summary=roundSummary(data,1,9);
 assert.equal(summary.status,'Updated Harness retained');
 assert(summary.retainedChanges>0);
 assert.equal(summary.retained,'accepted-r1');
});
test('baseline summary does not list later proposed edits',()=>{
 const summary=roundSummary(data,0,9);
 assert.equal(summary.status,'Initial Harness');
 assert.equal(summary.retained,'baseline');
 assert.deepEqual(summary.proposed,[]);
});
