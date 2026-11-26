import {test} from 'node:test';
import assert from 'node:assert/strict';
import example from '../../examples/component-history.example.json';
import type {ComponentHistory} from './component-types';
import {roundPage,roundPageGraph} from './component-round-page';
const data=example as unknown as ComponentHistory;

test('round pages expose only their own starting, candidate and retained snapshots',()=>{
  const first=roundPage(data,1,9),second=roundPage(data,2,9);
  assert.deepEqual(first.pages,[0,1,2,3]);
  assert.equal(first.step,3);
  assert.deepEqual(first.snapshots.map(row=>row.bundle.id),['baseline','trial-r1','accepted-r1']);
  assert.deepEqual(second.snapshots.map(row=>row.bundle.id),['accepted-r1','trial-r2','accepted-r2']);
  assert.equal(first.defaultSnapshot?.bundle.id,'accepted-r1');
  assert.equal(second.defaultSnapshot?.bundle.id,'accepted-r2');
  assert.deepEqual(roundPage(data,0,9).snapshots.map(row=>row.bundle.id),['baseline']);
});
test('a rejected round can retain the same snapshot without inventing a new Harness',()=>{
  const copy=structuredClone(data);
  copy.steps[6].active_bundle_id='accepted-r1';
  const page=roundPage(copy,2,9);
  assert.equal(page.defaultSnapshot?.id,'result:accepted-r1');
  assert.equal(page.snapshots[0].bundle.id,page.defaultSnapshot.bundle.id);
  assert(page.snapshots.some(row=>row.bundle.id==='trial-r2'));
});
test('an unfinished page never reveals future candidates or a selection',()=>{
  const page=roundPage(data,2,5),graph=roundPageGraph(data,2,5,1100);
  assert.equal(page.step,5);
  assert(!page.snapshots.some(row=>row.id.startsWith('result:')));
  assert(!graph.nodes.some(node=>node.id.endsWith(':boundary:2')));
  assert(!graph.nodes.some(node=>node.data.versionId==='subagent-v3'));
});
test('one page renders one round and keeps actual parents, including older rejected branches',()=>{
  const copy=structuredClone(data);
  copy.versions.find(version=>version.id==='subagent-v3')!.parent_id='subagent-v2';
  const graph=roundPageGraph(copy,3,9,1100);
  assert(graph.nodes.every(node=>node.data.round===3));
  assert(!graph.nodes.some(node=>node.data.versionId==='plugin-v0'));
  const edge=graph.edges.find(edge=>edge.id==='parent:subagent-v3')!;
  const source=graph.nodes.find(node=>node.id===edge.source)!;
  assert.equal(source.data.versionId,'subagent-v2');
  assert(source.data.caption.startsWith('Earlier'));
  for(const edge of graph.edges) {
    assert(graph.nodes.some(node=>node.id===edge.source));
    assert(graph.nodes.some(node=>node.id===edge.target));
  }
});
test('page geometry stays vertically stable and every component has the same lane height',()=>{
  const graphs=[0,1,2,3].map(round=>roundPageGraph(data,round,9,1100));
  assert.equal(new Set(graphs.map(graph=>graph.height)).size,1);
  for(const graph of graphs) {
    assert.equal(new Set([...graph.rows.values()].map(row=>row.height)).size,1);
    for(const node of graph.nodes) {
      const row=graph.rows.get(node.data.componentId)!;
      assert(node.position.y>row.top+32 && node.position.y<row.top+row.height-8);
      assert(node.position.x>=40 && node.position.x<=graph.width-26);
    }
  }
});

test('the diagram ends at evaluation without an extra retained column or handoff',()=>{
  const graph=roundPageGraph(data,2,9,1100);
  assert.deepEqual(graph.stages.map(stage=>stage.label),['Start','Candidate','Evaluation']);
  assert(!graph.edges.some(edge=>edge.data?.kind==='retained'));
  assert(!graph.nodes.some(node=>node.id.endsWith(':boundary:2')));
  assert(graph.nodes.some(node=>node.data.stage==='test' && node.data.rejected));
  assert(graph.page.snapshots.some(snapshot=>snapshot.id.startsWith('result:')));
});
