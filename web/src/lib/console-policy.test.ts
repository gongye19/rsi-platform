import {test} from 'node:test';
import assert from 'node:assert/strict';
import {componentPolicyForRun,type Policy} from './console-types';
const fields=['batch_tool','primary_tools','continue_loop_on_deny','mcp_timeout','disable_paste_summary'];
test('selecting the experimental channel admits its supported fields and preserves declaration choices',()=>{
 const source:Policy={allowed:['skills','experimental_policies'],denied:[],experimental_fields:['mcp_timeout'],proposal_only:['diagnostic']};
 const policy=componentPolicyForRun(source,fields);
 assert.deepEqual(policy.experimental_fields,fields);
 assert.deepEqual(policy.proposal_only,['diagnostic']);
 assert.deepEqual(source.experimental_fields,['mcp_timeout']);
});
test('deselecting the experimental channel removes stale field permissions without changing other channels',()=>{
 const policy=componentPolicyForRun({allowed:['skills'],denied:['experimental_policies'],experimental_fields:fields,proposal_only:[]},fields);
 assert.deepEqual(policy.experimental_fields,[]);
 assert.deepEqual(policy.allowed,['skills']);
 assert.deepEqual(policy.denied,['experimental_policies']);
 assert.deepEqual(policy.proposal_only,[]);
});
