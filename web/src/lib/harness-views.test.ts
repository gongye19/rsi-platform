import { test } from "node:test";
import assert from "node:assert/strict";
import example from "../../examples/component-history.example.json";
import type { ComponentHistory } from "./component-types";
import { harnessViews } from "./harness-views";
const data = example as unknown as ComponentHistory;
test("H0 contains the complete initial component tuple", () => {
  const views = harnessViews(data, 0);
  assert.equal(views.length, 1);
  assert.equal(views[0].label, "H0");
  for (const c of data.components)
    assert.equal(views[0].bundle.components[c.id], c.baseline_version_id);
});
test("a Harness exposes exactly its changed and inherited versions", () => {
  const h1 = harnessViews(data, 9)[1];
  assert.equal(h1.label, "H1");
  assert.equal(h1.bundle.components.system_prompt, "system_prompt-v1");
  assert.equal(h1.bundle.components.subagent, "subagent-v1");
  for (const c of data.components.filter(
    (c) => !["system_prompt", "subagent"].includes(c.id),
  ))
    assert.equal(h1.bundle.components[c.id], c.baseline_version_id);
});
test("identical trial and adopted configurations reuse one Harness identity", () => {
  const views = harnessViews(data, 9);
  const candidate = views.find((v) => v.bundleIds.includes("trial-r3"))!;
  assert(candidate.bundleIds.includes("accepted-r3"));
  assert.equal(views.length, 6);
});
test("replay hides future configurations and preserves established labels", () => {
  const past = harnessViews(data, 6),
    full = harnessViews(data, 9);
  assert.equal(past.length, 5);
  assert(past.every((v) => v.firstStep <= 6));
  for (const v of past)
    assert.equal(full.find((g) => g.id === v.id)?.label, v.label);
});
