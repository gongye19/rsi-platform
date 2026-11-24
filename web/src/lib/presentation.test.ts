import { test } from "node:test";
import assert from "node:assert/strict";
import { lineageZoom, measurementDomain, preferredLineagePercent } from "./presentation";

test("local axes contain every observation with symmetric room and never turn missing values into zero", () => {
  for (const values of [[203.51, 212.4], [21000, 25000], [62, 82], [-3, 1]]) {
    const [low, high] = measurementDomain(values);
    assert(low < Math.min(...values));
    assert(high > Math.max(...values));
    const centre = ((Math.min(...values) + Math.max(...values)) / 2 - low) / (high - low);
    assert(centre > 0.35 && centre < 0.65);
  }
  assert.deepEqual(measurementDomain([null, undefined, NaN, Infinity]), [0, 1]);
  const [low, high] = measurementDomain([0]);
  assert.equal(low, 0);
  assert(high > 0);
  assert(measurementDomain([120])[0] < 120 && measurementDomain([120])[1] > 120);
});
test("lineage scales up across displays while preserving the available vertical budget", () => {
  const laptop = lineageZoom(710, 540, 560);
  const desktop = lineageZoom(1080, 900, 560);
  const large = lineageZoom(1400, 1260, 560);
  assert.equal(laptop, 1);
  assert(desktop > laptop && large > desktop);
  assert(desktop * 560 <= 900 - 38 + 1);
  assert(large * 560 <= 1260 - 38 + 1);
  assert.equal(lineageZoom(700, 300, 560), 1);
  assert(lineageZoom(4000, 3000, 560) <= 1.7);
});
test("automatic split reserves more room for lineage on laptops and balances wider displays", () => {
  assert.equal(preferredLineagePercent(1280), 60);
  assert.equal(preferredLineagePercent(1920), 58);
  assert.equal(preferredLineagePercent(3440), 56);
});
