# Strata experiment console

## Direction and reference evidence

English product UI; Chinese user-facing updates. The user confirmed the Linear light reference set on 2026-11-26. The latest request uses two separate full-width chart views, quiet experiment deletion and a floating rounded configuration drawer. This supersedes the earlier side-by-side visualization and flush drawer.

Approved references actually inspected:
- [Linear project directory](https://mobbin.com/screens/3d3a4fae-d824-440a-961b-001c6b715a4a): neutral selection, compact text records and hierarchy.
- [Linear project detail](https://mobbin.com/screens/344cad59-d4a8-421a-9c2f-14b3c977e82d): restrained surfaces and metadata.
- [Linear creation flow](https://mobbin.com/flows/4b89331f-e3c0-44f7-bfb8-f4d3485f3c13?tab=screens): all seven frames inspected; compact controls and completion feedback, adapted to the requested drawer.
- [Linear general settings flow](https://mobbin.com/flows/76d2e1b8-d840-49ad-955f-9b371b579bc1?tab=screens): all five team-settings frames inspected; aligned label/value rows and grouping. No team features or automatic saving introduced.
- [Linear Help drawer](https://mobbin.com/flows/e0451091-e059-45c7-848d-1c5f796585a3?tab=screens): both entry/open frames inspected at full resolution and explicitly approved this round. Borrow inset edges, rounded surface and shallow shadow. Animation timing is a local implementation choice, not established by static screenshots.
- [MILO public demos](https://jprithwish.github.io/MILO/#demos): lineage and rejected branches as evidence, alongside results. Visualization reference only.

Linear's actual login entry did not expose an authenticated workspace. Styling derives from approved Mobbin imagery, not invented computed measurements. Static screens do not establish keyboard, hover, failure or responsive behavior. The existing accessible controls cover those states, with local browser verification. Native system sans is used consistently without a font CDN. The platform is branded Strata; HarnessLens remains the optimization package.

## Core flow

Choose a recorded experiment from the compact left list → inspect key results → switch between **Lineage** and **Evaluation**, each using the full content width.

Click **New experiment** in the left list or main header → right-side drawer opens over the current experiment → choose a benchmark independently of the runtime profile, initial Harness, execution/analysis models, allowed components and evolution settings → **Start run** generates an ID, persists the immutable configuration, then queues that exact experiment → drawer closes and the main view follows the new run. No manual Run ID, Save draft or internal paths for generated outputs appear in the creation form.

Each inactive experiment has a trash button with a compact confirmation. Deletion quietly removes the record from the directory after a Cancel/Delete confirmation. Files and evaluation evidence are retained server-side; no success notification or Undo is displayed. Active queued/running/stopping experiments must be stopped first. A persisted tombstone prevents imported CLI runs from reappearing on refresh. Restore never queues execution.

Cancel, Close or Escape dismisses the drawer without creating or launching anything. During submission, duplicate submission and drawer dismissal are disabled. The settings are retained while the drawer is open. Reopening a dismissed new-run drawer starts from the selected profile defaults.

**Run settings** opens the same drawer area with frozen, read-only settings for the selected experiment. No settings are edited in the main page. Viewing results, opening either drawer or selecting a snapshot never launches an experiment.

## State contract

| State | Display and actions |
| --- | --- |
| Empty | Main-page New experiment entry and concise setup guidance |
| Configuring | One drawer form; readiness and validation govern Start run |
| Submitting | Fields and actions disabled; persist before queue, never auto-retry creation |
| Creation error | Drawer retains the configuration and shows error |
| Uncertain creation / start error | Recover by the generated identity; show persisted run and its actual state |
| Draft | Existing draft can still be started from its main-page action |
| Queued / running | Actual phase, bounded updates and Stop |
| Stopping | Stop requested, without claiming remote calls were cancelled |
| Failed / interrupted / stopped | Evidence retained and visible failure; Resume for service-owned runs |
| Completed / imported | Frozen selected version and original TRAIN / TEST measurements |
| Deleted | Hidden from the directory; no success notification or Undo is shown |
| Connection error | Last records retained with a visible error and refresh |

## Layout and component mapping

- Left: 34px single-line records, experiment name and meaningful status dot only; long names ellipsize with full name/state in the tooltip. Search remains. No per-row score, benchmark, attempt metadata, extra status filter, Research workspace or decorative navigation icons.
- New experiment has a primary button in both the left directory and main header; the empty main page has the same entry.
- Main: compact key-result summary, actual run controls and the evolution view. Artifacts, Activity, raw JSON and their navigation links are hidden from this interface. Storage, trace collection and backend endpoints are preserved.
- A floating right drawer, at most 640px wide, sits 12px from the edges with a 14px radius, light gray border and soft shadow. Radix `data-state` triggers a 220ms entry and 180ms exit animation; reduced-motion uses near-instant transitions. It reuses the existing Sheet and accessible Select/Input/Button controls. Header and Cancel/Start actions stay fixed; only form fields scroll. All setting values share aligned left/right edges. Advanced timeout/retry fields stay collapsed initially. Model credentials remain server-owned. No extra library added.
- Read-only settings show benchmark, models, initial Harness, TEST choice, allowed components and primary evolution parameters; internal raw JSON is omitted.
- Two tabs, **Lineage** and **Evaluation**, show one full-width chart at a time. Keyboard arrow keys switch tabs. Round and snapshot selection stay in shared parent state; the split divider is removed. Each component owns an equal-height card. Its colored name repeats at the start of each round inside the card so horizontal pan retains identity. Names and their branches use the same color; per-row spacing is uniform, with enough room for all branch tracks. Vertical scrolling replaces compression of the entire 16-lane chart. The 16 component colors remain consistent across names, branches, versions and configuration checkboxes. Dashes/crosses convey state independently of color.
- Both charts retain 14px/500 headings, 11px/400 labels, 1.8px strokes and 8px normal points. Missing measurements remain empty. The evolution workspace keeps a 600px minimum height; component cards scroll vertically inside it instead of shrinking their contents.
- Existing evidence sheets still show component snapshots and adoption decisions; the link into Artifacts is omitted. No demo, playback, fabricated progress or metrics.

## Acceptance and verification

- Experiment deletion is authenticated and transactionally rejects active runs. Service tests cover delete/restore, imported tombstones, missing records and active-state protection. No model requests are made.
- Both New experiment buttons open a right drawer without changing the selected experiment or URL. Cancel/Close/Escape returns to the same view.
- No Run ID input, Artifacts/Activity tab, Save draft action or raw configuration control appears.
- All left records are 34px high, and settings controls share left/right edges.
- Execution and analysis choices are independent; component and budget edits work within the drawer. Header/footer stay visible while scrolling. Automatic identity generation happens only on Start run; existing launch helper still persists before queueing.
- Original metrics, retained version and actual backend states remain intact. No paid optimization run is started for UI validation.
- TypeScript, lint, production build, 41 frontend tests and 38 service/settings tests pass. Browser checks cover equal-height component cards, native vertical scrolling, branch evidence, independent chart views, benchmark choices/custom descriptor input, and deletion of an agent-created disposable draft with no follow-up notification. Narrow CSS is reviewed; no device emulation claim.
- Latest proof: `runs/platform/directory-ui.png`, `runs/platform/console-ui.png` (lineage), `runs/platform/evaluation-ui.png` (curves), `runs/platform/configuration-ui.png`, `runs/platform/configuration-components-ui.png`.

## Latest configuration contract

Benchmark is an independent selector populated from existing adapters (CRM, Tau² Retail/Banking, BIRD and Terminal-Bench), plus Custom benchmark with a server-side TOML descriptor path. Runtime profile selects the agent connection/environment. The selected benchmark is validated and saved into the immutable experiment snapshot; it does not silently fall back to CRM. Adapter selection does not assert that each dataset/runtime is installed. Custom task files and splits are validated before the snapshot is saved, without invoking a model or scorer.

Deletion shows one confirmation with Cancel/Delete, then quietly removes the row. No success banner or Undo button. Existing recoverable storage semantics remain server-side. Browser validation uses a disposable draft, never a business experiment.

Component evidence uses the inspected configuration first when a version belongs to several bundles; an unrelated rejected bundle must not supply the verdict for an unchanged initial component.

## Explicit round inspection

The Round selector and recorded round headers choose a persistent round. The lineage view shows a compact summary of proposed component edits, the retained Harness, retained tuple changes, pending/parent-retained/updated status and the recorded bundle decision reason. Component chips open the corresponding proposed snapshot. Counts describe edits and selected tuples, never individual test passes. Hover remains transient for chart linking and does not replace the summary. Selecting a round scrolls to its first proposed component and highlights that round’s column and branches; other rounds are subdued. Pan controls are hidden when all rounds fit. Closing candidate evidence restores focus to its trigger.

Browser checks verified Commands/candidate-01 for Round 01 and Skills/candidate-02 for Round 02, both retaining v0, as well as the correct candidate evidence. No model call or experiment launch was made.
