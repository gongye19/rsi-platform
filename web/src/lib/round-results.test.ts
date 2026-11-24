import { test } from "node:test";
import assert from "node:assert/strict";
import example from "../../examples/component-history.example.json";
import type { ComponentHistory } from "./component-types";
import { roundResults } from "./round-results";
const data = example as unknown as ComponentHistory;
test("one result per completed round comes from the adopted bundle, not a rejected trial", () => {
  const points = roundResults(data, 9, "score");
  assert.deepEqual(
    points.map((p) => p.round),
    [0, 1, 2, 3],
  );
  assert.deepEqual(
    points.map((p) => p.bundle?.id),
    ["baseline", "accepted-r1", "accepted-r2", "accepted-r3"],
  );
});
test("a proposed or evaluated round does not publish future adopted results", () => {
  assert.deepEqual(
    roundResults(data, 5, "score").map((p) => p.round),
    [0, 1],
  );
  assert.deepEqual(
    roundResults(data, 6, "score").map((p) => p.round),
    [0, 1, 2],
  );
});
test("missing measurements are gaps, including when the adopted bundle has no score", () => {
  const d = structuredClone(data);
  d.bundles.find((b) => b.id === "accepted-r2")!.metrics.score = null;
  assert.equal(roundResults(d, 9, "score")[2].value, null);
});
test("a rollback to an old bundle preserves its measurement provenance", () => {
  const d = structuredClone(data);
  d.steps[6].active_bundle_id = "accepted-r1";
  const r = roundResults(d, 6, "score")[2];
  assert.equal(r.bundle?.id, "accepted-r1");
  assert.equal(r.reused, true);
  assert.equal(
    r.value,
    d.bundles.find((b) => b.id === "accepted-r1")!.metrics.score,
  );
});

test("three metrics align on the same retained snapshot without filling missing scores", async () => {
  const { combinedRoundResults } = await import("./round-results");
  const d = structuredClone(data);
  d.bundles.find((b) => b.id === "accepted-r2")!.metrics.score = null;
  const points = combinedRoundResults(d, 9);
  assert.equal(points[2].score, null);
  assert.equal(
    points[2].seconds,
    d.bundles.find((b) => b.id === "accepted-r2")!.execution.seconds,
  );
  assert.equal(
    points[2].tokens,
    d.bundles.find((b) => b.id === "accepted-r2")!.execution.tokens,
  );
  assert.deepEqual(
    points.map((p) => p.round),
    [0, 1, 2, 3],
  );
});
