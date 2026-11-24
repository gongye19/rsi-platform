import { test } from "node:test";
import assert from "node:assert/strict";
import example from "../../examples/component-history.example.json";
import type { ComponentHistory } from "./component-types";
import { componentGraph } from "./component-graph";
import { advanceReplay, replayDuration } from "./replay";

const data = example as unknown as ComponentHistory;
test("tall displays use vertical space without stretching horizontal branch lengths", () => {
  const normal = componentGraph(data, 9);
  const tall = componentGraph(data, 9, 850, true);
  assert.equal(tall.layout.height, 850);
  for (const node of normal.nodes) {
    const next = tall.nodes.find((n) => n.id === node.id)!;
    assert.equal(next.position.x, node.position.x);
    assert(next.position.y < 850);
  }
  assert(tall.layout.rows.get("plugin")!.center > 750);
});
test("React Flow links actual parent versions, including a revived rejected branch", () => {
  const modified = structuredClone(data);
  modified.versions.find((v) => v.id === "subagent-v3")!.parent_id = "subagent-v2";
  const graph = componentGraph(modified, 9, 540);
  const edge = graph.edges.find((e) => e.id === "parent:subagent-v3")!;
  assert.equal(graph.nodes.find((n) => n.id === edge.source)!.data.versionId, "subagent-v2");
  assert.equal(graph.nodes.find((n) => n.id === edge.source)!.data.rejected, true);
  assert(!graph.edges.some((e) => e.data!.kind === "retained" && e.data!.versionId === "subagent-v2"));
});
test("each round shares a centred handoff and never fabricates future decisions", () => {
  const graph = componentGraph(data, 9, 540);
  for (const component of data.components) {
    assert.equal(graph.nodes.filter((n) => n.id === `${component.id}:boundary:1`).length, 1);
    const handoff = graph.nodes.find((n) => n.id === `${component.id}:boundary:1`)!;
    assert.equal(handoff.position.y, graph.layout.rows.get(component.id)!.center);
  }
  const proposed = componentGraph(data, 1, 540);
  assert(proposed.nodes.some((n) => n.data.stage === "experiment"));
  assert(!proposed.nodes.some((n) => n.data.stage === "test" || n.data.rejected));
  assert(!proposed.nodes.some((n) => n.id.endsWith(":boundary:1")));
});
test("all component outcomes remain in the experiment and only selected versions reach the next round", () => {
  const graph = componentGraph(data, 3, 540);
  assert.equal(new Set(graph.nodes.filter((n) => n.data.stage === "test").map((n) => n.data.componentId)).size, 8);
  assert.equal(graph.edges.filter((e) => e.data!.kind === "retained").length, 8);
  assert(!graph.edges.some((e) => e.source === "system_prompt-v1:tested:1"));
  assert(graph.nodes.some((n) => n.data.caption === "未优化"));
});
test("playback consumes presentation time continuously and preserves boundaries at any frame rate", () => {
  assert.equal(advanceReplay(data, 0.4, 0), 0.4);
  assert.equal(advanceReplay(data, 0, replayDuration(data, 0)), 1);
  const delta = replayDuration(data, 0) + replayDuration(data, 1) / 2;
  assert.equal(advanceReplay(data, 0, delta), 1.5);
  let position = 0;
  for (let i = 0; i < 100; i++) position = advanceReplay(data, position, delta / 100);
  assert(Math.abs(position - 1.5) < 0.00001);
  assert.equal(advanceReplay(data, 0, 999999), data.steps.length);
});
