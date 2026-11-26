# Experiment console

## Confirmed direction (2026-11-26)

The user approved Mobbin-led dashboard work and explicitly retained **component lineage on the left, result curves on the right**. The console UI is English; conversational updates remain Chinese. No new workflow builder, chat, billing, teams or reference-product features are added.

Current references, explicitly selected by the user on 2026-11-26:
- [Linear project directory](https://mobbin.com/screens/3d3a4fae-d824-440a-961b-001c6b715a4a): a compact registry with status and result columns, neutral gray surfaces, dark text and a restrained indigo accent. The user subsequently chose Linear colors for the whole platform.
- [Mercury overview](https://mobbin.com/screens/dbf9eb63-dcfe-4876-965a-e8a6d8702092): earlier hierarchy reference; its warm palette and serif title were superseded by the user’s Linear color preference.
- [MILO, AWS AI Labs and collaborators](https://jprithwish.github.io/MILO/#demos): persistent lineage with rejected children kept as evidence and results alongside it. This reference informs visualization only; no MILO search algorithm, island model or playback controls are introduced.

The earlier n8n / Langdock references are superseded for visual styling. Screenshots were actually inspected. Direct website checks reached Mercury's login page and Linear's public site, not authenticated workspaces; app styling is based on the approved Mobbin images. MILO's actual public interactive demo was inspected. Unmeasured reference dimensions and fonts are not presented as facts.

The platform is branded **Strata**, independently of its optimization algorithm. HarnessLens remains the name of the underlying package/algorithm. The local IBM Plex Sans font is shipped with its OFL license under `web/public/fonts`; no runtime font CDN is needed. All workspace headings now use the same sans-serif family.

## Core flow

Open the experiment directory → filter/search/select a real run or New experiment → select a server-owned benchmark profile → select independent execution/analysis models, editable components and evolution settings → Start run → save an immutable configuration and queue the backend job → follow persisted checkpoints and lineage → inspect final TRAIN/TEST results, configuration, artifacts and activity. Save draft is optional. Viewing history never launches an experiment.

## State contract

| State | Display and available actions |
| --- | --- |
| New | Configuration form, no invented baseline or results; Start enabled only after valid ready configuration |
| Draft | Frozen settings, Start; editing requires a new run |
| Queued | Queued badge, Stop; no simulated graph progress |
| Running | Last persisted checkpoint, live lineage/curves, Stop, automatic bounded refresh |
| Stopping | Stop requested; no claim the remote business call was cancelled |
| Stopped/interrupted/failed | Retained evidence and error; Resume for service-owned runs only |
| Completed | Frozen selected version and measured TRAIN/TEST; no playback or scrubber |
| Imported | Read-only history, with original repeats and metrics preserved |
| Connection error | Visible error, preserved last data, retry; never show stale data as live |

## Layout and components

A persistent workspace navigation provides All experiments, In progress, Drafts and Completed filters, with backend counts. The directory contains experiment identity, status, benchmark, TRAIN baseline, final TEST, selected version and creation date. Opening a record uses the existing `?run=` URL; breadcrumbs return to the full directory. Closing configuration preserves the current directory or record.

Run detail keeps the resizable lineage panel on the left and retained-result curves on the right, defaulting to equal 50:50 widths at every breakpoint. Both panels have matching padding, title height and plot boundaries. Dragging changes the split; double-clicking the separator restores equal widths. Narrow containers scroll horizontally rather than silently changing the ratio. When a round exceeds the canvas width, focusing it brings candidate/evaluation/selected endpoints into view; horizontal pan remains available for earlier parents. Component labels are fixed outside the horizontally pannable graph. Unchanged lanes use neutral ink; new versions use the purple accent and rejection has an explicit cross. Missing metrics remain unavailable, shown as a dash with an explanatory title. Snapshot selection and round inspection focus the matching recorded round. Snapshot controls, round context and an overflow menu replace the repeated toolbar labels and separate legend strip.

Reuse existing Button, Input, Select, Sheet, Popover, Chart and Resizable components. Keep React Flow for lineage and Recharts for measurements. The directory is a semantic table, with explicit buttons for keyboard navigation. No new npm dependencies. The palette follows the approved Linear reference: cool white/gray surfaces, neutral dark text and indigo actions, with semantic success/error colors. The summary and graph preserve TRAIN / TEST provenance and immutable run settings.

## Acceptance

- Both existing URLs open the same console and preserve the selected run.
- Start creates and starts exactly the selected configuration; launch failure preserves and identifies its draft.
- No example switcher, Play/Pause, speed control, playback timeline or synthetic percentage remains.
- The graph follows backend artifacts, not a presentation clock; selecting prior rounds is inspection only.
- No initial Harness appears until its actual snapshot exists; missing metrics remain unavailable.
- Component names, controls, accessible names, metadata and empty/error states are English.
- Imported runs cannot Start/Resume; service-owned jobs retain Stop/Resume behavior.
- Modal focus/close, keyboard inputs, long IDs, scroll and narrow layout are checked in-browser.

## Verified implementation

- Both console routes serve successfully; the selected run stays in the URL.
- Browser: independent model selection, component toggles, numeric settings and Save draft preserve their exact server snapshot. The validation draft was not launched.
- Browser: final TEST artifact opens, version inspection shows its recorded rejection reason, and the evidence action opens that run's artifact tab.
- Browser DOM reports `lang=en`, no Chinese UI text on Overview, zero replay controls and zero sliders.
- Frontend: type check, lint, production build and 41 unit tests pass. Launch tests cover save-before-start order, failure without retry, preserved drafts and draft-only behavior.
- Backend: the CRM/business/service/runtime regression group passes (131 tests, 2 skips), plus the new live non-v0-parent preflight regression passes.
- The real experiment was imported and inspected; validation did not start a new paid optimization experiment. Small-height windows scroll the workspace vertically to retain readable component lanes.

## 2026-11-26 refinement validation

- TypeScript, lint, production build and the existing 41 frontend unit tests pass.
- In-browser: directory status filters/counts, name search, open record, close configuration without losing context, snapshot/round selection, graph panning with fixed component names, and component evidence inspection were checked.
- Bundled Plex Sans loads successfully. The Overview DOM has all 16 fixed component labels, English document language and zero playback sliders.
- The local browser offers no viewport emulation; narrow-screen CSS was reviewed in source rather than claimed as a device test. Small-height desktop windows scroll vertically to retain readable lanes.
- Validation did not launch a paid model experiment. The API and worker were preserved during frontend-only restarts.
- Current proof images: `runs/platform/directory-ui.png`, `runs/platform/console-ui.png`, `runs/platform/configuration-ui.png`.

## Linear palette and equal-width refinement

The user explicitly requested Linear colors and equal panel proportions. Removed the adaptive 60/40–56/44 layout and its obsolete unit test. The remaining 40 frontend tests, type checking, lint and production build pass. Browser measurements and splitter reset are recorded in the current UI verification images.

Browser verification at the current desktop viewport: each panel is 490.5px wide; both plotting regions are 458.5px × 413px with an identical top coordinate. Keyboard resize changes the split and double-click restores exactly 50:50. The configuration sheet still opens and closes normally. No model experiment was launched.
