# RSI Platform experiment console

## Direction and reference evidence

English product UI; Chinese user-facing updates. The user confirmed the Linear light reference set on 2026-11-26. The latest request uses a full-height, one-round-per-page lineage view, a separate evaluation chart, quiet experiment deletion and a floating rounded configuration drawer. This supersedes the earlier side-by-side visualization and flush drawer.

Approved references actually inspected:
- [Linear project directory](https://mobbin.com/screens/3d3a4fae-d824-440a-961b-001c6b715a4a): neutral selection, compact text records and hierarchy.
- [Linear project detail](https://mobbin.com/screens/344cad59-d4a8-421a-9c2f-14b3c977e82d): restrained surfaces and metadata.
- [Linear creation flow](https://mobbin.com/flows/4b89331f-e3c0-44f7-bfb8-f4d3485f3c13?tab=screens): all seven frames inspected; compact controls and completion feedback, adapted to the requested drawer.
- [Linear general settings flow](https://mobbin.com/flows/76d2e1b8-d840-49ad-955f-9b371b579bc1?tab=screens): all five team-settings frames inspected; aligned label/value rows and grouping. No team features or automatic saving introduced.
- [Linear Help drawer](https://mobbin.com/flows/e0451091-e059-45c7-848d-1c5f796585a3?tab=screens): both entry/open frames inspected at full resolution and explicitly approved this round. Borrow inset edges, rounded surface and shallow shadow. Animation timing is a local implementation choice, not established by static screenshots.
- [MILO public demos](https://jprithwish.github.io/MILO/#demos): lineage and rejected branches as evidence, alongside results. Visualization reference only.

Linear's actual login entry did not expose an authenticated workspace. Styling derives from approved Mobbin imagery, not invented computed measurements. Static screens do not establish keyboard, hover, failure or responsive behavior. The existing accessible controls cover those states, with local browser verification. Native system sans is used consistently without a font CDN. The platform is branded RSI Platform; HarnessLens remains the optimization package.

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
- A floating right drawer, at most 720px wide, sits 12px from the edges with a 14px radius, light gray border and soft shadow. Radix `data-state` triggers a 220ms entry and 180ms exit animation; reduced-motion uses near-instant transitions. It reuses the existing Sheet and accessible Select/Input/Button controls. Header and Cancel/Start actions stay fixed; only form fields scroll. All setting values share aligned left/right edges. Advanced timeout/retry fields stay collapsed initially. Model credentials remain server-owned. No extra library added.
- Read-only settings show benchmark, models, initial Harness, TEST choice, allowed components and primary evolution parameters; internal raw JSON is omitted.
- Two tabs, **Lineage** and **Evaluation**, show one full-width chart at a time. Keyboard arrow keys switch tabs. Round and snapshot selection stay in shared parent state; the split divider is removed. Each component owns an equal-height card. Its colored name sits inside the card above the current round’s version chain. Names and their branches use the same color; per-row spacing is uniform, with enough room for all branch tracks. Vertical scrolling replaces compression of the entire 16-lane chart. The 16 component colors remain consistent across names, branches, versions and configuration checkboxes. Dashes/crosses convey state independently of color.
- Both charts use 18px headings, 14px labels and consistent thin strokes. Missing measurements remain empty. The lineage workspace expands to the complete diagram height and scrolls with the main page; the evaluation chart keeps a readable fixed height.
- Existing evidence sheets still show component snapshots and adoption decisions; the link into Artifacts is omitted. No demo, playback, fabricated progress or metrics.

## Acceptance and verification

- Experiment deletion is authenticated and transactionally rejects active runs. Service tests cover delete/restore, imported tombstones, missing records and active-state protection. No model requests are made.
- Both New experiment buttons open a right drawer without changing the selected experiment or URL. Cancel/Close/Escape returns to the same view.
- No Run ID input, Artifacts/Activity tab, Save draft action or raw configuration control appears.
- All left records are 34px high, and settings controls share left/right edges.
- Execution and analysis choices are independent; component and budget edits work within the drawer. Header/footer stay visible while scrolling. Automatic identity generation happens only on Start run; existing launch helper still persists before queueing.
- Original metrics, retained version and actual backend states remain intact. No paid optimization run is started for UI validation.
- TypeScript, lint, production build and 58 frontend tests pass. Browser checks cover equal-height component cards, main-page scrolling, round pagination and snapshots, branch evidence and independent chart views. Prior checks cover benchmark choices/custom descriptor input and deletion of an agent-created disposable draft with no follow-up notification. Narrow CSS is reviewed; no device emulation claim.
- Latest proof: `runs/platform/directory-ui.png`, `runs/platform/console-ui.png` (lineage), `runs/platform/evaluation-ui.png` (curves), `runs/platform/configuration-ui.png`, `runs/platform/configuration-components-ui.png`.

## Latest configuration contract

Benchmark is an independent selector populated from existing adapters (CRM, Tau² Retail/Banking, BIRD and Terminal-Bench), plus Custom benchmark with a server-side TOML descriptor path. Runtime profile selects the agent connection/environment. The selected benchmark is validated and saved into the immutable experiment snapshot; it does not silently fall back to CRM. Adapter selection does not assert that each dataset/runtime is installed. Custom task files and splits are validated before the snapshot is saved, without invoking a model or scorer.

Deletion shows one confirmation with Cancel/Delete, then quietly removes the row. No success banner or Undo button. Existing recoverable storage semantics remain server-side. Browser validation uses a disposable draft, never a business experiment.

Component evidence uses the inspected configuration first when a version belongs to several bundles; an unrelated rejected bundle must not supply the verdict for an unchanged initial component.

## Round pages and page scrolling

Core flow: open an experiment → inspect the latest recorded round → Previous / Next round → select a snapshot from that round → inspect a component version. Baseline is a separate first page. Both top and bottom pagination controls expose the current round and page count. The Round dropdown and the multi-round horizontal canvas are removed.

The main console owns vertical scrolling. All 16 component lanes grow to their natural height; there is no second vertical scroll area inside the diagram. Sidebar navigation remains fixed. One responsive, read-only React Flow canvas shows Start → Candidate → Evaluation for the current round. Existing colored component cards, version buttons and evidence sheets are reused. Narrow screens may horizontally scroll this single round without reducing text size.

| State | Visible behavior |
| --- | --- |
| Baseline | Initial Harness and all initial components; Previous disabled |
| Completed round | Its own starting, candidate and retained snapshots; recorded changes and adoption reason |
| Rejected candidate | Candidate remains inspectable; retained snapshot can equal the starting Harness |
| Unfinished round | Only recorded candidates and outcomes; no invented selected configuration |
| Older rejected parent reused | Explicit earlier-version reference preserves the real parent edge |
| Last recorded page | Next disabled; new live rounds become available when recorded |

Snapshot choices are derived from the selected round's event interval, including its starting Harness and recorded selection. Selecting a snapshot highlights its component tuple and component headings open those versions. Paginating resets to that round's retained snapshot (latest candidate while pending). No later candidate, adoption decision or verdict appears in an earlier page. Unchanged Harnesses keep their original identity rather than acquiring a new snapshot ID merely because the round changed.

Acceptance: scroll over the diagram directly to the last component and bottom pager; render only the selected round; previous/next update summary, branches and snapshot choices together; preserve main scroll position within available page bounds; keep version evidence and the separate Evaluation chart functional. Six focused round-page tests cover temporal boundaries, rejection, real ancestry and consistent lanes, alongside the frontend regression suite. Browser validation uses actual recorded executions without launching an experiment.

## Public presentation mode

Product branding is **RSI Platform**. Production demo: <https://rsi-platform-demo.vercel.app/experiments>.

The dedicated Vercel project `rsi-platform-demo` builds only the frontend with `NEXT_PUBLIC_RSI_DEMO=1`. It has no experiment service URL, service token, model credentials, private benchmark files or real experiment records. This flag replaces console reads/actions and lineage reads with a browser-local adapter; the server proxy also refuses upstream calls in demo mode. Source uploads exclude local environment files, examples, tests, logs and the Python backend.

The sample history is synthetic: 16 components, three rounds, two retained updates, one rejected candidate, and illustrative score/time/token measurements. New runs simulate progress in about 30 seconds under the default budget. Configuration, creation and deletion are local to each browser; visitors do not share records. Other benchmark choices demonstrate configuration with the same illustrative 13-task evaluation pattern. No dataset, filesystem or model is actually accessed. The visible Demo badge and simulation messages distinguish this mode from real execution.

The normal local/intranet build leaves this flag unset and continues to use the authenticated experiment service. Demo mode is opt-in and does not change actual stored experiments.

## Presentation readability and component boundaries

The workspace uses 15px body and control text, 13–14px supporting labels, 18px chart headings and 24px page headings. Sidebar records stay compact at 38px. Configuration controls use 36px height and the floating drawer allows up to 720px width. Diagram and evaluation labels share a 14px visual scale.

Changing the selected lineage round replaces the single-round page and its snapshots, with scroll position preserved within available bounds. Wide single-round diagrams retain native horizontal scrolling.

Configuration separates 16 editable components from 5 declaration-only categories (model/provider, runtime environment, file attachments, tool outputs and diagnostics). Declaration selections are frozen into the profile and sent to discovery as recommendation permissions. They never become executable edit channels. Existing profiles default to all five; an explicit empty list disables all such recommendations. The console selects the Experimental policies channel as a whole. Its supported field allowlist is filled automatically on task creation and stays hidden in the UI; deselecting the channel submits an empty field list. The optimizer chooses specific edits inside that boundary. The separate five declaration-only categories remain individually selectable. Existing run policies are not rewritten.

## Compact experiment header and lineage density

The experiment header contains the run name/status and compact benchmark/date metadata. The only persistent metrics are TRAIN baseline, final TEST and used/total budget, on one inline strip. Trial counts and remaining budget are available in native tooltips; the final Harness is in Run settings. A duplicate New experiment action is removed from the selected-run header; the primary sidebar action remains. Active runs still show their actual execution phase and Stop/Resume controls. Repeated Evolution/Recorded results headings and duplicate round/page labels are omitted.

Each round summary is one compact row: proposed component links, recorded adoption status and Details. Details opens an existing Popover with the full reason, selected Harness and change count; it does not resize the page. Baseline keeps its component count. The snapshot selector remains scoped to the current round and uses short Start/Candidate/Selected labels.

The diagram ends at Evaluation. The separate Retained column, its duplicate nodes and handoff edges are removed from this projection only; retained snapshots, adoption outcomes and actual ancestry remain in the data. Component lanes shrink from approximately 128px to 88px for the current recorded run, with additional room only when branch tracks or earlier-parent references require it. Text remains 14–15px and the 16 colors stay unchanged. The page retains one outer vertical scrollbar and single-round pagination.

Browser verification covers the three columns, compact metrics, per-round component changes, full reason popover, independent evaluation chart and scrolling through all components. Bottom pagination keeps the recorded scroll offset (1280px before and after). Current proof: `runs/platform/round-page-ui.png` and `runs/platform/round-page-bottom-ui.png`. No model requests or experiments are launched.

## Changed-first lineage and project libraries

The latest user request replaces the all-component canvas with native component
cards. Each round shows proposed/changed components first, followed by a closed
**Unchanged components** disclosure. Baseline still exposes all initial components.
Colors follow the original component index even after reordering. Start, Candidate
and Evaluation occupy the available width; evaluation labels align inside the right
edge. Visible version tracks are distributed symmetrically above/below the fork.
No synthetic pass/fail or new version identity is introduced.

Click a component heading, candidate chip or version to open its content in place.
A changed version compares its actual parent on the left and that version on the
right. Added/removed files have an explicit missing side. Full recorded snapshots
are rendered as content; historical patch-only records are labelled **Recorded
change** without claiming reconstructed full files. Shared leading/trailing lines
remain neutral and the changed block is highlighted. Decision evidence remains
available in an inline disclosure. There is no component evidence side drawer.
Round pagination supplies the recorded round context. The redundant Snapshot
selector is removed; component rows directly open the proposed version against
its actual parent (or the current version for an unchanged component).

Configuration integrates domain and task counts directly under Benchmark. Both
limits and optional grouping come from the adapter. No declared domain means a
single all-task pool and no domain selector. Builtins and custom benchmarks are
discovered from `benchmarks/<id>/benchmark.toml`; the separate Dataset section and
custom server-path input are removed. Runtime connection profiles remain separate.

Initial Harness is a Select populated from `harnesses/`, with **Empty Harness** as
the first choice. Local experiment starts archive an immutable initial package and
subsequent frozen versions below `harnesses/<run-id>/`. Existing recorded runs can
be backfilled from their actual frozen initial snapshot. Only final selections are
marked Selected. CLI/profile paths stay compatible. These files stay ignored by
Git; only the directory instructions and builtin benchmark registrations ship.

Browser checks cover changed-first ordering, 15 unchanged components hidden by
default, opening/closing their disclosure, inline before/after content and real
candidate evidence, CRM without domains, FDABench with domain-dependent limits,
and selecting actual archived candidate versions. No experiment/model is launched.
Latest proof: `runs/platform/component-comparison-ui.png` and
`runs/platform/harness-library-ui.png`. Previous round-page screenshots are
superseded by these views.

## Lineage controls and whole-row disclosure

The chart tabs occupy their own top row. Round pagination and legend
controls are rendered inside the Lineage tab panel on the next row and are absent
from Evaluation. The separate proposed-component/status/Details summary is removed:
the component itself exposes its versions, content comparison and decision evidence.
The duplicate lineage instruction footnote is also omitted.

Each component uses one native full-width disclosure button. Its name sits in a
fixed left column, vertically aligned with the diagram. Hover highlights the row;
there is no permanent left stripe, disclosure chevron or decorative dot. Clicking the name,
a version label, a branch or empty space in that row toggles the same comparison;
Enter/Space work through normal button semantics. The expanded comparison is outside
the button, so file disclosures and text selection do not collapse the component.
No nested interactive controls or competing click targets remain in the row.

Sibling paths share the same short trunk and fork interval, regardless of their
final endpoint distance. Both curves reach equally spaced rails early and then run
horizontally to their version nodes. An unchanged/assessed version stays horizontal.
The left-name column is included in responsive width calculations, preserving the
right-edge evaluation marks and a native horizontal fallback on narrow screens.

Evaluation endpoints use a green circled check for the recorded selected version
and a red circled cross for a version not retained. Retained paths are solid;
rejected paths are dashed, including the candidate's incoming branch. Component
colors still identify the tracks. An unresolved evaluation uses an empty
circle. A passing component check alone never implies adoption. Version identity
and outcome remain in hover tooltips and accessible descriptions; detailed evidence
is available inside the component comparison. Endpoint labels and status captions
are not repeated on the diagram. The source and candidate labels remain visible.

Validation: frontend tests, targeted lint, TypeScript and production build pass.
Browser checks confirm whole-row empty-space click to open/close, keyboard toggle,
independent file disclosures, Lineage-only controls, no Snapshot dropdown or name
decorations, icon-only endpoints, no duplicate summary, and outcome line styles.
Latest layout proof: `runs/platform/lineage-layout-ui.png`.

## Held-out evaluation instead of training-subset curves

The console's Evaluation tab now reads `Run.tests.initial` and
`Run.tests.selected`, not per-iteration TRAIN bundle metrics. It shows only TEST
Baseline and Final. Missing scores remain absent, with a waiting state if neither
exists. A retained v0 explicitly reuses its initial TEST result. The summary also
uses TEST baseline so its two scores are comparable. Intermediate TRAIN trials
remain available through the Lineage component comparisons; they do not become
TEST points. No additional model calls or evaluation jobs are introduced.

Current orchestration in `harnesslens/service/experiment.py` executes TRAIN first
(including its full selected TRAIN baseline and candidate-subset iterations), then
freezes the final submission, evaluates initial v0 on the selected TEST split, and
evaluates a different selected version if applicable. Initial TEST is computed
after training in this implementation, without feeding its results into selection.
There is no outer loop that repeatedly evaluates TEST after each candidate. A
train-only profile has no fabricated TEST curve. Latest evaluation proof:
`runs/platform/test-evaluation-ui.png`.

## Focused benchmark catalog

New experiment offers CRM Arena Pro and FDABench Lite · Reports only, in both the
local console and the public demo's simulated configuration. Unused native
registration manifests are removed; directory discovery stays generic and custom
benchmark registrations can still be added later. Native CLI adapters and existing
experiment records are preserved. Proof: `runs/platform/benchmark-options-ui.png`.
