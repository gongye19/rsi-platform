import { test } from "node:test";
import assert from "node:assert/strict";
import example from "../../examples/harnesslens-history.example.json";
import catalog from "../../examples/opencode-1.18.32-components.json";
import type { ComponentHistory } from "./component-types";
import { componentGraph } from "./component-graph";
import { combinedRoundResults } from "./round-results";

const data = example as unknown as ComponentHistory;
test("HarnessLens uses the fixed 16-component profile and does not relabel Harness² history", () => {
  assert.equal(data.profile?.version, "1.18.32");
  assert.equal(data.source, "example");
  assert.equal(data.components.length, 16);
  assert.deepEqual(data.components.map(c => c.id), catalog.components.map(c => c.id));
  assert(!data.components.some(c => ["guardrails", "memory", "tool_guidance", "script"].includes(c.id)));
  assert(data.decisions.every(d => d.scope === "bundle" && ["retained", "not_retained"].includes(d.outcome)));
});
test("a rejected HarnessLens candidate does not become a new incumbent or measurement", () => {
  const points = combinedRoundResults(data, data.steps.length - 1);
  assert.deepEqual(points.map(p => p.score), [62, 71, 71, 77]);
  assert(points.find(p => p.round === 2)?.reused);
  const graph = componentGraph(data, data.steps.length - 1, 490, true);
  assert.equal(graph.nodes.find(n => n.id === "system_prompt:boundary:2")?.data.versionId, "system_prompt-v1");
  const edge = graph.edges.find(e => e.id === "parent:tool_description-v2")!;
  assert.equal(graph.nodes.find(n => n.id === edge.source)?.data.versionId, "tool_description-v0");
});
test("all 16 component lanes and outcomes stay within the viewport budget", () => {
  for (const height of [400, 490, 800, 1200]) {
    const graph = componentGraph(data, data.steps.length - 1, height, true);
    assert.equal(graph.layout.rows.size, 16);
    assert(graph.nodes.every(n => n.position.y >= 0 && n.position.y + 14 <= height));
    for (const round of [1, 2, 3]) {
      assert.equal(graph.nodes.filter(n => n.data.stage === "test" && n.data.round === round && !n.data.rejected).length, 16);
    }
  }
});
