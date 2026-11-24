/** Keep dense lineage readable without magnifying a narrow panel beyond one round. */
export function lineageZoom(width: number, height: number, naturalHeight: number) {
  return Math.round(Math.max(1, Math.min(1.7, (height - 38) / naturalHeight, width / 560)) * 1000) / 1000;
}

export function preferredLineagePercent(width: number) {
  return width < 1500 ? 60 : width < 2400 ? 58 : 56;
}

/** Local, padded axes distribute measurements through the plot instead of against its ceiling.
 * No values are changed, and finite zero measurements remain genuine measurements.
 */
export function measurementDomain(values: (number | null | undefined)[]): [number, number] {
  const finite = values.filter((n): n is number => typeof n === "number" && Number.isFinite(n));
  if (!finite.length) return [0, 1];
  const low = Math.min(...finite), high = Math.max(...finite);
  const spread = high - low;
  const padding = Math.max(spread * 0.65, Math.abs(high) * 0.05, spread === 0 ? Math.abs(high) * 0.2 : 0, 0.001);
  return [low >= 0 ? Math.max(0, low - padding) : low - padding, high + padding];
}
