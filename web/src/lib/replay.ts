import type { ComponentHistory } from "./component-types";

/** Presentation time only. Never interpret this as elapsed execution time. */
export function replayDuration(data: ComponentHistory, step: number) {
  const event = data.steps[step];
  const count = data.versions.filter((v) => v.step === step && v.parent_id).length;
  if (count) return 1600 + Math.min(900, count * 130);
  if (event?.kind === "test") return 2200;
  if (event?.kind === "select") return 1500;
  return step === 0 ? 900 : 1400;
}

/** Consume elapsed playback time across event boundaries without dropping frames. */
export function advanceReplay(data: ComponentHistory, position: number, milliseconds: number) {
  const end = data.steps.length;
  let next = Math.max(0, Math.min(position, end));
  let remaining = Math.max(0, milliseconds);
  while (next < end && remaining > 0) {
    const step = Math.floor(next);
    const duration = replayDuration(data, step);
    const needed = (step + 1 - next) * duration;
    if (remaining < needed) return next + remaining / duration;
    remaining -= needed;
    next = step + 1;
  }
  return next;
}
