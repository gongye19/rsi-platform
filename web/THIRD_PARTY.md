# UI component provenance

The Button, Badge, Input, Table, Skeleton, Tooltip and Sheet component wrappers were reused from the existing local project `estate-client/src/components/ui`, using its shadcn/ui (Radix Nova) implementations. They are adapted only for this application's imports and theme. No estate business code or data was copied.

shadcn/ui is MIT licensed: https://github.com/shadcn-ui/ui/blob/main/LICENSE.md

The lineage uses React Flow (@xyflow/react 13.0.3, MIT), with custom version nodes, Bézier edges and event-reveal masks. Reference: https://reactflow.dev/ . License: https://github.com/xyflow/xyflow/blob/main/LICENSE . React Flow attribution remains visible.

The user-selected visual reference is the MILO evolution demo: https://jprithwish.github.io/MILO/#demos . Its blue (#2a78d6), purple (#7d3c98), rose (#d55181), neutral text and faint lane backgrounds inform the theme. No MILO algorithm or experimental results were copied.

Radix UI, Lucide and the remaining package licenses are distributed with their installed packages. Package versions are locked in `bun.lock`.

The round-results chart now uses Recharts 3.8.0 and the official shadcn/ui ChartContainer/Tooltip implementation. The split view uses shadcn/ui Resizable with react-resizable-panels 4.x. Sources (MIT):
- https://github.com/shadcn-ui/ui/blob/main/apps/v4/registry/new-york-v4/ui/chart.tsx
- https://github.com/shadcn-ui/ui/blob/main/apps/v4/registry/new-york-v4/ui/resizable.tsx
- https://github.com/recharts/recharts/blob/main/LICENSE
- https://github.com/bvaughn/react-resizable-panels/blob/main/LICENSE.md

The component layout and projection preserve recorded parent/version/round data. React Flow provides the canvas and interaction; no generic layout is allowed to alter version ancestry.

Select and Slider wrap the already-installed Radix UI primitives (MIT); Popover reuses the existing estate-client shadcn wrapper. All three use the experiment theme. No additional runtime package was added. Reference: https://www.radix-ui.com/primitives/docs/components/select and https://www.radix-ui.com/primitives/docs/components/slider .
