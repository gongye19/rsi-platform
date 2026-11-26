# Strata experiment console

## Direction and reference evidence

English product UI; Chinese user-facing updates. The user confirmed the Linear light reference set on 2026-11-26. The latest request simplifies the interface and restores a **right-side configuration drawer**. This supersedes the earlier full-page editor preference.

Approved references actually inspected:
- [Linear project directory](https://mobbin.com/screens/3d3a4fae-d824-440a-961b-001c6b715a4a): neutral selection, compact text records and hierarchy.
- [Linear project detail](https://mobbin.com/screens/344cad59-d4a8-421a-9c2f-14b3c977e82d): restrained surfaces and metadata.
- [Linear creation flow](https://mobbin.com/flows/4b89331f-e3c0-44f7-bfb8-f4d3485f3c13?tab=screens): all seven frames inspected; compact controls and completion feedback, adapted to the requested drawer.
- [Linear general settings flow](https://mobbin.com/flows/76d2e1b8-d840-49ad-955f-9b371b579bc1?tab=screens): all five team-settings frames inspected; aligned label/value rows and grouping. No team features or automatic saving introduced.
- [MILO public demos](https://jprithwish.github.io/MILO/#demos): lineage and rejected branches as evidence, alongside results. Visualization reference only.

Linear's actual login entry did not expose an authenticated workspace. Styling derives from approved Mobbin imagery, not invented computed measurements. Static screens do not establish keyboard, hover, failure or responsive behavior. The existing accessible controls cover those states, with local browser verification. Native system sans is used consistently without a font CDN. The platform is branded Strata; HarnessLens remains the optimization package.

## Core flow

Choose a recorded experiment from the compact left list → inspect key results, component lineage and retained result curves.

Click **New experiment** in the left list or main header → right-side drawer opens over the current experiment → choose benchmark profile, initial Harness, execution/analysis models, allowed components and evolution settings → **Start run** generates an ID, persists the immutable configuration, then queues that exact experiment → drawer closes and the main view follows the new run. No manual Run ID, Save draft or internal paths for generated outputs appear in the creation form.

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
| Connection error | Last records retained with a visible error and refresh |

## Layout and component mapping

- Left: 34px single-line records, experiment name and meaningful status dot only; long names ellipsize with full name/state in the tooltip. Search remains. No per-row score, benchmark, attempt metadata, extra status filter, Research workspace or decorative navigation icons.
- New experiment has a primary button in both the left directory and main header; the empty main page has the same entry.
- Main: compact key-result summary, actual run controls and the evolution view. Artifacts, Activity, raw JSON and their navigation links are hidden from this interface. Storage, trace collection and backend endpoints are preserved.
- A 640px right drawer reuses the existing Sheet and accessible Select/Input/Button controls. Header and Cancel/Start actions stay fixed; only form fields scroll. All setting values share aligned left/right edges. Advanced timeout/retry fields stay collapsed initially. Model credentials remain server-owned. No extra library added.
- Read-only settings show benchmark, models, initial Harness, TEST choice, allowed components and primary evolution parameters; internal raw JSON is omitted.
- The lineage/results view keeps resizable **50:50** panels, double-click reset and fixed component names during horizontal pan. The 16 component colors remain consistent across names, branches, versions and configuration checkboxes. Dashes/crosses convey state independently of color.
- Both charts retain 14px/500 headings, 11px/400 labels, 1.8px strokes and 8px normal points. Missing measurements remain empty. The 600px minimum evolution workspace prevents lane overlap in shorter windows; the main surface scrolls.
- Existing evidence sheets still show component snapshots and adoption decisions; the link into Artifacts is omitted. No demo, playback, fabricated progress or metrics.

## Acceptance and verification

- Both New experiment buttons open a right drawer without changing the selected experiment or URL. Cancel/Close/Escape returns to the same view.
- No Run ID input, Artifacts/Activity tab, Save draft action or raw configuration control appears.
- All left records are 34px high, and settings controls share left/right edges.
- Execution and analysis choices are independent; component and budget edits work within the drawer. Header/footer stay visible while scrolling. Automatic identity generation happens only on Start run; existing launch helper still persists before queueing.
- Original metrics, retained version and actual backend states remain intact. No paid optimization run is started for UI validation.
- TypeScript, lint, production build and the existing 40 unit tests pass. Browser checks cover both entry points, closing, settings, selection, drawer editing, scrolling and the 50:50 visualization. Narrow CSS is reviewed; no device emulation claim.
- Latest proof: `runs/platform/directory-ui.png`, `runs/platform/console-ui.png`, `runs/platform/configuration-ui.png`, `runs/platform/configuration-components-ui.png`.
