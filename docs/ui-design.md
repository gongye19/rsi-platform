# Experiment console

## Current direction

The English platform is branded **Strata**; HarnessLens remains the underlying optimization package/algorithm. User-facing updates are Chinese. Keep the approved Linear-style cool neutrals/indigo, 16 component colors and **equal-width lineage left / retained-result curves right**.

The latest user preference restores the **experiment list on the left** while keeping all runtime configuration together in the main content area. No Research workspace identity, nested workspace navigation or decorative navigation icons return.

References actually inspected:
- [Linear project directory](https://mobbin.com/screens/3d3a4fae-d824-440a-961b-001c6b715a4a): neutral surfaces, compact records and text hierarchy.
- [MILO public demos](https://jprithwish.github.io/MILO/#demos): recorded lineage and rejected branches kept as evidence alongside results. Visualization reference only; no MILO island algorithm or playback is introduced.

Direct Linear access reached its public site, not an authenticated workspace. Styling derives from the approved Mobbin screenshot, not invented computed measurements. Earlier Mercury/n8n/Langdock styling is superseded. IBM Plex Sans is bundled with its OFL license under `web/public/fonts`, with no runtime font CDN.

## Core flow

Select a real run in the left list → Overview / Configuration / Artifacts / Activity. New experiment in that same list opens a complete configuration page in the main area → choose the benchmark profile, independent execution/analysis models, component boundaries, initial Harness, evolution/timeout/retry/concurrency settings and TEST evaluation → Save draft or Start run → persist the immutable configuration before queueing that exact run → follow backend checkpoints and inspect evidence.

Viewing a run, switching tabs, choosing a snapshot or opening the editor never launches an experiment. Existing run settings remain frozen; configuration changes require a new experiment.

## State contract

| State | Display and actions |
| --- | --- |
| New | One editor with all inputs in the same form; validation and profile readiness govern Start |
| Draft | Frozen configuration and Start; appears in the experiment list |
| Queued/running | Actual persisted phase, live bounded refresh, Stop |
| Stopping | Stop requested, without claiming cancellation of a remote business call |
| Stopped/interrupted/failed | Preserved evidence and error; Resume only for service-owned runs |
| Completed | Frozen selected version and measured TRAIN / TEST results |
| Imported | Original metrics/repeats and model receipts, read only |
| Connection error | Visible error, last received data preserved, refresh/recovery |

## Layout and component mapping

- Left: a compact text-based experiment list with search, one status filter, New experiment, selected record and actual state/measurement. No workspace card, workflow explainer or decorative row icons. Long names wrap.
- Main: run title and actual operational actions, summary and tabs. Run configuration has one tab containing the frozen model, component and parameter settings; duplicate Configure new run buttons are removed.
- New experiment: a full configuration page, not a sheet or modal. Profile / Run ID / Initial Harness are together; experimental field allowlists sit with the editable components. The entire editor is one form and uses the main page scroll. Save draft and Start run share its sticky footer.
- Overview: existing React Flow lineage and Recharts curves in resizable 50:50 panels. Double-clicking the separator resets equal widths. Both plots share typography, padding and plot boundaries.
- Component names stay fixed during horizontal pan. Each of the 16 components has one consistent color across names, nodes and ancestry; dashes and rejection crosses convey state independently of color. Text colors retain contrast against white.
- Both visualizations use 14px/500 headings, 11px/400 data labels, 1.8px main strokes and 8px normal points. Canvas text/glyphs compensate for zoom. The active chart point is 10px.
- Snapshot selection inspects recorded versions. The overflow control is explicitly labeled Legend and measurement notes; it contains explanations, not a second configuration surface.

Reuse the existing Button, Input, Select, Sheet (component evidence only), Popover, Chart and Resizable components. No new npm dependencies. Model credentials remain server-owned. No simulated progress, demo data switcher, playback or slider is added.

## Acceptance and validation

- Left-side list search/filter/record selection and the selected run URL work; root opens a real active/latest recorded run, or New experiment when empty.
- New experiment opens the central editor, with all editable inputs and both submission actions in one form and no configuration dialog.
- Execution and analysis selections are independent; budget and component changes update that same configuration. Save-before-start and failure recovery preserve the client-generated identity without automatic creation retries.
- Existing run Configuration displays its frozen model connections, allowed/denied components, experimental fields, initial Harness, TEST choice and parameter labels together.
- Historical TRAIN/TEST provenance, missing metrics, retained snapshots and bundle-scoped decisions are preserved. No initial Harness is invented before an actual initial snapshot.
- TypeScript, lint, production build and the existing 40 frontend unit tests pass. Browser verification covers independent model changes, budget/component changes, same-form inputs, sticky footer, left-list navigation, and frozen configuration viewing. No paid model experiment is started during validation.
- The local browser has no viewport emulation; narrow CSS is reviewed in source rather than claimed as a device test. Small-height desktop windows scroll the main page.
- Current proof: `runs/platform/directory-ui.png` (left list / run summary), `runs/platform/console-ui.png` (lineage/results), `runs/platform/configuration-ui.png` (central editor).

A transient list-reading stall in the long-running local API process was recovered by restarting that API after confirming zero active jobs. Direct list reads then returned all four records in about 15ms. No backend source changes were required, and experiment records and the worker were retained.
