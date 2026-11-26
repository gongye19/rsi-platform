import {test} from 'node:test';
import assert from 'node:assert/strict';
import {lineageBranchPath} from './lineage-branch';
test('retained and candidate rails use a mirrored fork regardless of endpoint distance',()=>{
  const a=lineageBranchPath({x:40,y:44},{x:900,y:31},460);
  const b=lineageBranchPath({x:40,y:44},{x:460,y:57},460);
  assert.equal(a,'M 40 44 L 92 44 C 124 44, 140 31, 172 31 L 900 31');
  assert.equal(b,'M 40 44 L 92 44 C 124 44, 140 57, 172 57 L 460 57');
});
test('a carried or assessed version stays horizontal without an unnecessary bend',()=>{
  assert.equal(lineageBranchPath({x:100,y:30},{x:400,y:30}),'M 100 30 L 400 30');
});
test('short branches keep their fork inside the nearest endpoint',()=>{
  const path=lineageBranchPath({x:100,y:30},{x:130,y:50});
  assert(path.endsWith('L 130 50'));
  assert(!path.includes('NaN'));
  assert(path.includes('121 50'));
});
