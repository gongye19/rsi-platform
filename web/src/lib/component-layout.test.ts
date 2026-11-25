import { test } from "node:test";
import assert from "node:assert/strict";
import example from "../../examples/component-history.example.json";
import type { ComponentHistory } from "./component-types";
import {
  componentLayout,
  experimentResults,
  evolutionRounds,
  roundChanges,
} from "./component-layout";
const data = example as unknown as ComponentHistory;
test("round two starts with V1, rejects V2, and round three branches from retained V1", () => {
  const rounds = evolutionRounds(data);
  const second = roundChanges(data, rounds[1], 9).find(
    (c) => c.component.id === "subagent",
  )!;
  assert.equal(second.before, "subagent-v1");
  assert.equal(second.after, "subagent-v1");
  assert.equal(second.rollback, true);
  assert.deepEqual(
    second.rejected.map((v) => v.id),
    ["subagent-v2"],
  );
  const third = roundChanges(data, rounds[2], 9).find(
    (c) => c.component.id === "subagent",
  )!;
  assert.equal(third.before, "subagent-v1");
  assert.equal(third.generated[0].parent_id, "subagent-v1");
  assert.equal(third.after, "subagent-v3");
});
test("unselected bundle components do not acquire failed-test grades", () => {
  const bundleOnly = structuredClone(data);
  bundleOnly.decisions = bundleOnly.decisions.map((d) => ({
    ...d,
    scope: "bundle",
    outcome: d.outcome === "failed" ? "not_retained" : "retained",
  }));
  const r = roundChanges(bundleOnly, evolutionRounds(bundleOnly)[0], 9);
  const prompt = r.find((c) => c.component.id === "system_prompt")!;
  assert(prompt.rollback);
  assert.equal(prompt.failed.length, 0);
});
test("replay reveals candidates before adoption, without leaking final decisions", () => {
  const r = roundChanges(data, evolutionRounds(data)[1], 4);
  const subagent = r.find((c) => c.component.id === "subagent")!;
  assert.equal(subagent.generated[0].id, "subagent-v2");
  assert.equal(subagent.after, undefined);
  assert.equal(subagent.rollback, false);
  assert.equal(subagent.failed.length, 0);
  assert.equal(r.find((c) => c.component.id === "skill")!.generated.length, 0);
});
test("unchanged components reuse version identities across every handoff", () => {
  for (const round of evolutionRounds(data)) {
    const memory = roundChanges(data, round, 9).find(
      (c) => c.component.id === "memory",
    )!;
    assert.equal(memory.before, "memory-v0");
    assert.equal(memory.after, "memory-v0");
    assert.equal(memory.generated.length, 0);
    assert.equal(memory.rollback, false);
  }
});
test("same-round generated versions have separate tracks inside their component", () => {
  const { positions, rows, width } = componentLayout(data);
  assert.equal(positions.size, data.versions.length);
  for (const c of data.components) {
    const versions = data.versions.filter((v) => v.component_id === c.id);
    for (const round of new Set(versions.map((v) => v.round))) {
      const peers = versions.filter((v) => v.round === round && v.parent_id);
      assert.equal(new Set(peers.map((v) => positions.get(v.id)!.y)).size, peers.length);
    }
    for (const v of versions) {
      const p = positions.get(v.id)!,
        row = rows.get(c.id)!;
      assert(p.y - 7 >= row.top);
      assert(p.y + 7 <= row.top + row.height);
      assert(p.x >= 140 && p.x < width);
    }
  }
});
test("additional idle events do not stretch existing branches", () => {
  const before = componentLayout(data),
    extended = structuredClone(data);
  extended.steps.push({ index: 10, round: 3, label: "idle", kind: "idle" });
  assert.deepEqual(componentLayout(extended).positions, before.positions);
});
test("an unfinished last round does not invent a selection", () => {
  const partial = structuredClone(data);
  partial.steps = partial.steps.slice(0, 9);
  const round = evolutionRounds(partial).at(-1)!;
  assert.equal(round.resolutionStep, undefined);
  assert.equal(round.result, undefined);
  assert(roundChanges(partial, round, 8).every((c) => !c.after));
});

test("fitting the window compresses only vertical spacing and preserves every horizontal branch", () => {
  const normal = componentLayout(data),
    fit = componentLayout(data, 420);
  assert.equal(fit.height, 420);
  for (const v of data.versions) {
    const p = fit.positions.get(v.id)!;
    assert.equal(p.x, normal.positions.get(v.id)!.x);
    assert(p.y > 80 && p.y + 12 < 420);
  }
  assert.equal(fit.rows.size, 8);
});

test("the same V2 label connects to V1 or V0 strictly according to parent_id", async () => {
  const { versionParentAnchor } = await import("./component-layout");
  const v = data.versions.find((v) => v.id === "subagent-v2")!;
  const layout = componentLayout(data);
  const fromV1 = versionParentAnchor(data, layout, v)!;
  assert.equal(fromV1.versionId, "subagent-v1");
  assert.equal(fromV1.kind, "input");
  assert.equal(fromV1.x, layout.inputX(1));
  const changed = structuredClone(data),
    v2 = changed.versions.find((item) => item.id === v.id)!;
  v2.parent_id = "subagent-v0";
  const changedLayout = componentLayout(changed);
  const fromV0 = versionParentAnchor(changed, changedLayout, v2)!;
  assert.equal(v2.label, "V2");
  assert.equal(fromV0.versionId, "subagent-v0");
  assert.equal(fromV0.kind, "origin");
  assert.equal(fromV0.x, changedLayout.positions.get("subagent-v0")!.x);
  assert.notEqual(fromV0.x, fromV1.x);
});

test("same-round children use their recorded parent node rather than the round start", async () => {
  const { versionParentAnchor } = await import("./component-layout");
  const changed = structuredClone(data);
  // Exercise a valid same-component branch chain with two same-round versions.
  const parent = changed.versions.find((v) => v.id === "subagent-v1")!;
  const v2 = changed.versions.find((v) => v.id === "subagent-v2")!;
  v2.round = 1;
  v2.step = 2;
  v2.parent_id = parent.id;
  const layout = componentLayout(changed),
    anchor = versionParentAnchor(changed, layout, v2)!;
  assert.equal(anchor.versionId, parent.id);
  assert.equal(anchor.kind, "origin");
  assert.equal(anchor.x, layout.positions.get(parent.id)!.x);
});

test("round frames enclose boundary nodes and the next round shares the retained endpoint", () => {
  const layout = componentLayout(data, 420);
  layout.rounds.forEach((r, i) => {
    const box = layout.roundBounds(i),
      right = box.x + box.width;
    assert(layout.inputX(i) - 13 > box.x);
    assert(layout.resultX(i) + 16 < right);
    assert(layout.resultX(i) + 13 < right);
    if (i < layout.rounds.length - 1)
      assert.equal(layout.resultX(i), layout.inputX(i + 1));
  });
});

test("a later child may branch from an unretained candidate without extending it toward the adopted result", async () => {
  const { versionParentAnchor } = await import("./component-layout");
  const changed = structuredClone(data);
  const child = changed.versions.find((v) => v.id === "subagent-v3")!;
  child.parent_id = "subagent-v2";
  const layout = componentLayout(changed),
    anchor = versionParentAnchor(changed, layout, child)!;
  assert.equal(anchor.versionId, "subagent-v2");
  assert.equal(anchor.kind, "origin");
  assert.equal(anchor.x, layout.positions.get("subagent-v2")!.x);
  assert.equal(anchor.y, layout.positions.get("subagent-v2")!.y);
  assert.notEqual(anchor.x, layout.inputX(2));
});

test("the experiment contains generation and full test results, separated from the next start", () => {
  const layout = componentLayout(data);
  layout.rounds.forEach((r, i) => {
    const phases = layout.phaseBounds(i);
    assert(phases.input.x <= layout.inputX(i));
    assert(layout.inputX(i) < phases.experiment.x);
    assert(layout.testX(i) > phases.test.x);
    assert(layout.testX(i) + 64 < layout.resultX(i));
    assert(layout.testX(i) < phases.test.x + phases.test.width);
    assert(layout.resultX(i) - 24 > phases.experiment.x + phases.experiment.width);
    for (const v of data.versions.filter(
      (v) => v.round === r.round && v.parent_id,
    )) {
      const p = layout.positions.get(v.id)!;
      assert(p.x - 5 > phases.experiment.x);
      assert(p.x + 5 < phases.test.x);
    }
  });
});

test("experiment results include passed, failed, unchanged and retained-original versions", () => {
  const first = experimentResults(data, evolutionRounds(data)[0], 9);
  assert.equal(new Set(first.map((o) => o.componentId)).size, data.components.length);
  assert.equal(first.find((o) => o.versionId === "subagent-v1")?.caption, "Passed");
  assert.equal(first.find((o) => o.versionId === "system_prompt-v1")?.caption, "Failed");
  assert.equal(first.find((o) => o.versionId === "system_prompt-v1")?.rejected, true);
  assert.equal(first.find((o) => o.versionId === "system_prompt-v0")?.caption, "Parent retained");
  assert.equal(first.find((o) => o.versionId === "memory-v0")?.caption, "Unchanged");
});

test("experiment outcomes do not leak future verdicts or invent individual test passes", () => {
  const first = evolutionRounds(data)[0];
  assert.deepEqual(experimentResults(data, first, 1), []);
  const bundleOnly = structuredClone(data);
  bundleOnly.decisions = bundleOnly.decisions.map((d) => ({
    ...d, scope: "bundle", outcome: d.outcome === "failed" ? "not_retained" : "retained",
  }));
  const results = experimentResults(bundleOnly, evolutionRounds(bundleOnly)[0], 9);
  assert(!results.some((o) => o.caption === "Passed" || o.caption === "Failed"));
  assert.equal(results.find((o) => o.versionId === "subagent-v1")?.caption, "Retained");
});

test("sibling candidates align horizontally; only actual same-round descendants advance", () => {
  const peers = structuredClone(data);
  const first = peers.versions.find((v) => v.id === "system_prompt-v1")!;
  peers.versions.push(
    { ...first, id: "prompt-peer-2", label: "V2", step: 2 },
    { ...first, id: "prompt-peer-3", label: "V3", step: 2 },
  );
  const aligned = componentLayout(peers);
  const ids = [first.id, "prompt-peer-2", "prompt-peer-3"];
  assert.equal(new Set(ids.map((id) => aligned.positions.get(id)!.x)).size, 1);
  assert.equal(new Set(ids.map((id) => aligned.positions.get(id)!.y)).size, 3);
  peers.versions.find((v) => v.id === "prompt-peer-2")!.parent_id = first.id;
  peers.versions.find((v) => v.id === "prompt-peer-3")!.parent_id = first.id;
  const chained = componentLayout(peers);
  assert(chained.positions.get("prompt-peer-2")!.x > chained.positions.get(first.id)!.x);
  assert.equal(chained.positions.get("prompt-peer-2")!.x, chained.positions.get("prompt-peer-3")!.x);
  assert(chained.testX(0) > aligned.testX(0));
});

test("each round starts at component centre, independent of the retained version's creation track", async () => {
  const { versionParentAnchor } = await import("./component-layout");
  const changed = structuredClone(data);
  const peer = changed.versions.find((v) => v.id === "subagent-v2")!;
  peer.round = 1;
  peer.step = 2;
  peer.parent_id = "subagent-v0";
  const layout = componentLayout(changed), center = layout.rows.get("subagent")!.center;
  assert.notEqual(layout.positions.get("subagent-v1")!.y, center);
  for (let i = 0; i < layout.rounds.length; i++)
    assert.equal(layout.boundaryPoint(i, "subagent").y, center);
  const next = changed.versions.find((v) => v.id === "subagent-v3")!;
  assert.equal(versionParentAnchor(changed, layout, next)!.y, center);
  assert.equal(layout.testPoint(1, "subagent-v1").y, center);
});
