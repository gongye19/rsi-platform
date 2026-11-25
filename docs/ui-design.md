# Experiment console

## Confirmed direction (2026-11-26)

The user approved Mobbin-led dashboard work and explicitly retained **component lineage on the left, result curves on the right**. The console UI is English; conversational updates remain Chinese. No new workflow builder, chat, billing, teams or reference-product features are added.

References:
- [n8n execution history](https://mobbin.com/screens/3de1bd57-5cbe-441e-89fd-df40985f3806): compact execution rows, consistent status badges and run selection.
- [Langdock workflow run](https://mobbin.com/flows/76e059cf-d211-470a-a885-5edc842d7a94?tab=screens): configure, launch and inspect recorded outputs. Its canvas/chat layout is not adopted.
- [n8n official execution documentation](https://docs.n8n.io/workflows/executions/all-executions/): separate execution status and history from configuration.

Screenshots were inspected at full resolution. No authenticated reference-product session was available; screenshots establish visual hierarchy, not keyboard/hover behavior. Controls below use the existing local Radix/shadcn components. Dimensions are project choices, not claimed measurements from Mobbin.

## Core flow

Select a real run or New experiment → select a server-owned benchmark profile → select independent execution/analysis models, editable components and evolution settings → Start run → save an immutable configuration and queue the backend job → follow persisted checkpoints and lineage → inspect final TRAIN/TEST results, configuration, artifacts and activity. Save draft is optional. Viewing history never launches an experiment.

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

One shell with a compact run sidebar and a main workspace. Main header aligns run identity, status and actions. A summary row precedes tabs for Overview, Configuration, Artifacts and Activity. Overview retains the existing resizable two-panel lineage/curve layout. Configuration opens in an accessible sheet; it never replaces the graph with an editor canvas. Small screens can horizontally scroll the graph area and open the run list without clipping actions.

Reuse Button, Input, Select, Sheet, Badge, Chart and Resizable components. Keep React Flow for lineage and Recharts for measurements. No new dependencies. A single 36px form-control height, shared spacing, neutral borders and blue primary actions apply to configuration and dashboard controls.

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
