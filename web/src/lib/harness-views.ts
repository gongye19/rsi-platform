import type {
  ComponentHistory,
  ConfigurationSnapshot,
} from "./component-types";
export interface HarnessView {
  id: string;
  label: string;
  bundle: ConfigurationSnapshot;
  bundleIds: string[];
  firstStep: number;
}
/** One Harness identity per complete tuple; repeated trials/adoptions reuse it. */
export function harnessViews(
  data: ComponentHistory,
  step: number,
): HarnessView[] {
  const all = new Map<string, HarnessView>();
  for (const bundle of [...data.bundles].sort((a, b) => a.step - b.step)) {
    const key = JSON.stringify(
      data.components.map((c) => [c.id, bundle.components[c.id]]),
    );
    let view = all.get(key);
    if (!view) {
      view = {
        id: bundle.id,
        label: `H${all.size}`,
        bundle,
        bundleIds: [],
        firstStep: bundle.step,
      };
      all.set(key, view);
    }
    if (bundle.step <= step) {
      view.bundleIds.push(bundle.id);
      view.bundle = bundle;
    }
  }
  return [...all.values()].filter((v) => v.bundleIds.length > 0);
}
