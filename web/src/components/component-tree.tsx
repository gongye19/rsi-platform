"use client";
import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  ReactFlow, ReactFlowProvider, Handle, Position, ViewportPortal,
  getBezierPath, useReactFlow,
  type EdgeProps, type NodeProps, type Viewport,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { ArrowLeft, ArrowRight, ScanLine } from "lucide-react";
import { componentGraph, type LineageBranch, type LineagePoint } from "@/lib/component-graph";
import { roundChanges } from "@/lib/component-layout";
import { COMPONENT_COLORS, type ComponentHistory } from "@/lib/component-types";

const VersionPoint = memo(function VersionPoint({ data }: NodeProps<LineagePoint>) {
  const style = {
    "--point-color": data.color,
    "--arrival-delay": data.delay,
  } as CSSProperties;
  return (
    <div className={`ce-flow-point ${data.arrival ? "is-arriving" : ""}`} style={style}>
      <Handle type="target" position={Position.Left} isConnectable={false} />
      <button
        className="ce-version nodrag nopan"
        data-version-id={data.versionId}
        data-node-role={data.stage}
        data-node-final={data.stage === "input" && !data.root && !data.contextName}
        data-graph-round={data.round}
        data-node-variant={data.rejected ? "rejected" : "normal"}
        aria-label={`${data.componentName} ${data.label}, ${data.caption || (data.stage === "experiment" ? "Candidate" : "Starting version")}, round ${data.round}`}
        title="Inspect version snapshot and evidence"
      >
        <span className="ce-node-glyph" aria-hidden="true">{data.rejected ? "×" : ""}</span>
        <span className="ce-version-label">{data.label}<small>{data.caption === "Unchanged" ? "" : data.caption === "Parent retained" ? "Retained" : data.caption}</small></span>
      </button>
      <Handle type="source" position={Position.Right} isConnectable={false} />
    </div>
  );
});

const Branch = memo(function Branch(props: EdgeProps<LineageBranch>) {
  const { data, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition } = props;
  if (!data) return null;
  const [path] = getBezierPath({ sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, curvature: 0.42 });
  const carried = data.kind === "held" || data.kind === "retained";
  const color = data.color;
  const style = {
    "--branch-delay": data.delay,
    stroke: color,
  } as CSSProperties;
  // A clip reveals both dashed and solid paths without changing their appearance.
  const clip = `reveal-${props.id.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
  return (
    <g
      data-connection={data.kind}
      data-version-edge={data.versionId}
      data-parent={data.parentId}
      data-graph-round={data.round}
      className={`ce-flow-branch ${data.arrival ? "is-arriving" : ""}`}
      style={style}
    >
      {data.arrival && <defs><mask id={clip} maskUnits="userSpaceOnUse" x={Math.min(sourceX, targetX) - 12} y={Math.min(sourceY, targetY) - 30} width={Math.abs(targetX - sourceX) + 24} height={Math.abs(targetY - sourceY) + 60}><path d={path} pathLength={1} className="ce-edge-reveal" fill="none" stroke="white" strokeWidth={12} /></mask></defs>}
      <path
        d={path}
        fill="none"
        strokeWidth={1.8}
        vectorEffect="non-scaling-stroke"
        strokeOpacity={carried ? 0.48 : data.rejected ? 0.6 : 0.88}
        strokeDasharray={carried ? "3 5" : undefined}
        mask={data.arrival ? `url(#${clip})` : undefined}
      />
    </g>
  );
});
const nodeTypes = { version: VersionPoint };
const edgeTypes = { branch: Branch };

type Props = {
  data: ComponentHistory;
  step: number;
  selected: string;
  onSelect: (id: string) => void;
  followLive: boolean;
  configuration?: Record<string, string>;
  selectedRound: number;
  focusedRound: number | null;
  focusRevision: number;
  onRound: (round: number) => void;
  onHoverRound: (round: number | null) => void;
};

function LineageCanvas({ data, step, selected, configuration, selectedRound, focusedRound, focusRevision, onRound, onHoverRound, onSelect, followLive }: Props) {
  const host = useRef<HTMLDivElement>(null);
  const scroll = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 620, height: 540 });
  const [initialized, setInitialized] = useState(false);
  const [viewport, setViewport] = useState<Viewport>({ x: 0, y: 0, zoom: 1 });
  const flow = useReactFlow<LineagePoint, LineageBranch>();
  const zoom = 1;
  const graph = useMemo(() => componentGraph(data, step, undefined, false, true), [data, step]);
  const { layout } = graph;
  const labelWidth = 0;
  const maxPan = Math.max(0, layout.width * zoom - size.width);
  const lastAutoRound = useRef<string | null>(null);
  const syncedScroll = useRef<number | null>(null);
  const focusedIndex = layout.rounds.findIndex(round=>round.round===selectedRound);
  const changedComponents = new Set(focusedIndex>=0 ? roundChanges(data,layout.rounds[focusedIndex],step).filter(change=>change.generated.length).map(change=>change.component.id) : []);

  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(([entry]) => setSize({ width: entry.contentRect.width, height: entry.contentRect.height }));
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);
  function moveTo(x: number, duration = 300) {
    void flow.setViewport({ x: Math.max(-maxPan, Math.min(0, x)), y: 0, zoom }, { duration });
  }
  useEffect(() => {
    const current = flow.getViewport();
    const x = Math.max(-maxPan, Math.min(0, current.x / current.zoom * zoom));
    void flow.setViewport({ x, y: 0, zoom });
  }, [flow, zoom, maxPan]);
  useEffect(() => {
    if (!initialized) return;
    // Hover links the score chart but must never move the canvas under the pointer.
    const targetRound = focusedRound ?? (followLive ? data.steps[step]?.round : null);
    const index = layout.rounds.findIndex((r) => r.round === targetRound && r.firstStep <= step);
    const requestKey = `${followLive ? "live" : "inspect"}:${targetRound}:${focusRevision}:${size.width}:${zoom}`;
    if (index < 0 || lastAutoRound.current === requestKey) return;
    lastAutoRound.current = requestKey;
    const x = index === 0 ? 0 : Math.max(0, layout.inputX(index) * zoom - labelWidth - 10);
    const end = (layout.resultX(index) + 32) * zoom;
    const current = flow.getViewport();
    if (x + current.x < 0 || end + current.x > size.width)
      void flow.setViewport({ x: -Math.min(maxPan, Math.max(x, end - size.width)), y: 0, zoom }, { duration: 500 });
  }, [initialized, focusedRound, focusRevision, data.steps, layout, flow, step, followLive, maxPan, size.width, zoom, labelWidth]);



  const nodes = useMemo(() => graph.nodes.map((node) => ({
    ...node,
    className: `${focusedIndex>=0 && (node.position.x<layout.inputX(focusedIndex)-1 || node.position.x>layout.resultX(focusedIndex)+1) ? "is-other-round" : "is-round-focus"} ${node.data.versionId === selected ? "is-inspected" : ""} ${configuration?.[node.data.componentId] === node.data.versionId ? "is-member" : ""}`,
  })), [graph.nodes, selected, configuration,focusedIndex,layout]);
  const edges = useMemo(() => graph.edges.map((edge) => ({
    ...edge, className: edge.data?.round === selectedRound ? "ce-linked-branch" : "ce-other-round",
  })), [graph.edges, selectedRound]);
  const onViewportChange = (next: Viewport) => {
    const clamped = { x: Math.max(-maxPan, Math.min(0, next.x)), y: 0, zoom };
    setViewport(clamped);
    if (scroll.current && Math.abs(scroll.current.scrollLeft + clamped.x) > 1) {
      syncedScroll.current = -clamped.x;
      scroll.current.scrollLeft = -clamped.x;
    }
  };
  return (
    <div
      className="ce-flow-host ce-uniform-lanes"
      ref={host}
      data-recorded-step={step}
      data-canvas-zoom={zoom}
      style={{ "--ce-canvas-zoom": zoom, height: layout.height + 34 } as CSSProperties}
      data-linked-round={selectedRound}
    >
      <ReactFlow<LineagePoint, LineageBranch>
        id="component-lineage"
        onInit={() => setInitialized(true)}
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        nodeOrigin={[0.5, 0.5]}
        defaultViewport={{ x: 0, y: 0, zoom }}
        onMove={(_, next) => onViewportChange(next)}
        translateExtent={[[0, 0], [Math.max(layout.width, size.width / zoom), size.height / zoom]]}
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        edgesFocusable={false}
        minZoom={zoom}
        maxZoom={zoom}
        zoomOnScroll={false}
        zoomOnPinch={false}
        zoomOnDoubleClick={false}
        panOnScroll={false}
        panOnDrag
        preventScrolling={false}
        onNodeClick={(_, node) => onSelect(node.data.versionId)}
        onNodeMouseEnter={(_, node) => onHoverRound(node.data.round)}
        onNodeMouseLeave={() => onHoverRound(null)}
        onPaneMouseMove={(event) => {
          const rect = host.current?.getBoundingClientRect();
          if (!rect) return;
          const x = (event.clientX - rect.left - viewport.x) / zoom;
          const index = layout.rounds.findIndex((_, i) => x >= layout.inputX(i) - 20 && x <= layout.resultX(i) + 20);
          const round = layout.rounds[index];
          onHoverRound(round && round.firstStep <= step ? round.round : null);
        }}
        onPaneClick={(event) => {
          const rect = host.current?.getBoundingClientRect();
          if (!rect) return;
          const x = (event.clientX - rect.left - viewport.x) / zoom;
          const index = layout.rounds.findIndex((_, i) => x >= layout.inputX(i) - 20 && x <= layout.resultX(i) + 20);
          const round = layout.rounds[index];
          if (round && round.firstStep <= step) onRound(round.round);
        }}
        onPaneMouseLeave={() => onHoverRound(null)}
      >
        <ViewportPortal>
          <svg className="ce-flow-backdrop" width={Math.max(layout.width, size.width / zoom)} height={layout.height} aria-hidden="true">
            {data.components.map((component,index) => {
              const row=layout.rows.get(component.id)!;
              return <g key={component.id}><rect x={4} y={row.top} width={Math.max(layout.width,size.width)-8} height={row.height} rx={8} fill="#fff" stroke={changedComponents.has(component.id)?COMPONENT_COLORS[index % COMPONENT_COLORS.length]:"#e7e7eb"} strokeOpacity={changedComponents.has(component.id)?.55:1}/>{focusedIndex>=0 && <rect x={layout.inputX(focusedIndex)-18} y={row.top+1} width={layout.resultX(focusedIndex)-layout.inputX(focusedIndex)+36} height={row.height-2} rx={7} fill="#5e6ad2" fillOpacity={.055}/>}<rect x={4} y={row.top+12} width={3} height={row.height-24} rx={1.5} fill={COMPONENT_COLORS[index % COMPONENT_COLORS.length]} opacity={.65}/></g>;
            })}
          </svg>
          {data.components.flatMap((component,index) => (layout.rounds.length ? layout.rounds : [{round:0}]).map((round,ri) => <button key={`${component.id}:${round.round}`} className="ce-lane-heading nopan nodrag" data-round-active={round.round===selectedRound} style={{left:layout.inputX(ri)-22,top:layout.rows.get(component.id)!.top+8,color:COMPONENT_COLORS[index % COMPONENT_COLORS.length]}} onClick={() => onSelect(configuration?.[component.id] || component.baseline_version_id)} aria-label={`Inspect ${component.name} in the selected snapshot, round ${round.round}`}><i/>{component.name}</button>))}
          {data.components.flatMap(component => layout.rounds.map((round,index) => <span key={`${component.id}:${round.round}`} className="ce-lane-round" aria-hidden="true" style={{left:layout.candidateX(index)+65,top:layout.rows.get(component.id)!.top+9}}>Round {String(round.round).padStart(2,'0')}</span>))}
          {layout.rounds.map((r, i) => {
            const visible = r.firstStep <= step;
            const count = visible ? roundChanges(data, r, step).filter((c) => c.generated.length).length : 0;
            return <div key={r.round} className={`ce-flow-round ${visible ? "" : "is-future"}`} style={{ left: layout.inputX(i) - 18, width: layout.resultX(i) - layout.inputX(i) + 36 }}>
              <button className="nopan nodrag" disabled={!visible} aria-pressed={selectedRound === r.round} onClick={() => onRound(r.round)} onMouseEnter={() => visible && onHoverRound(r.round)} onMouseLeave={() => onHoverRound(null)} onFocus={() => visible && onHoverRound(r.round)} onBlur={() => onHoverRound(null)} aria-label={`Inspect round ${r.round}`}>
                <span>Round {String(r.round).padStart(2, "0")}</span><small>{visible ? `${count} updated` : "Pending"}</small>
              </button>
              <span className="ce-phase-label" style={{ left: 18 }}>{i ? "Parent" : "Baseline"}</span>
              <span className="ce-phase-label" style={{ left: layout.candidateX(i) - layout.inputX(i) + 18 }}>Candidate</span>
              <span className="ce-phase-label" style={{ left: layout.testX(i) - layout.inputX(i) + 18 }}>Evaluation</span>
            </div>;
          })}
          <span className="ce-final-label" style={{ left: layout.resultX(Math.max(0, layout.rounds.length - 1)) - 20 }} title="Selected configuration">Selected</span>
        </ViewportPortal>
      </ReactFlow>
      {maxPan > 1 && <div className="ce-canvas-tools" style={{ left: 8, top: 8, bottom: 'auto' }}>
        <button aria-label="Pan left" disabled={viewport.x >= -1} onClick={() => moveTo(viewport.x + size.width * 0.7)}><ArrowLeft size={13} /></button>
        <button aria-label="Go to lineage start" onClick={() => moveTo(0)}><ScanLine size={14} /></button>
        <button aria-label="Pan right" disabled={viewport.x <= -maxPan + 1} onClick={() => moveTo(viewport.x - size.width * 0.7)}><ArrowRight size={13} /></button>
      </div>}
      <div ref={scroll} className="ce-canvas-scroll" onScroll={(e) => {
        const x = -e.currentTarget.scrollLeft;
        if (syncedScroll.current != null && Math.abs(e.currentTarget.scrollLeft - syncedScroll.current) < 1) {
          syncedScroll.current = null;
          return;
        }
        if (Math.abs(viewport.x - x) > 1) void flow.setViewport({ x, y: 0, zoom });
      }} aria-label="Pan component lineage" tabIndex={0}><div style={{ width: Math.max(size.width, layout.width * zoom), height: 1 }} /></div>
    </div>
  );
}

export default function ComponentTree(props: Props) {
  return <ReactFlowProvider key={props.data.id}><LineageCanvas {...props} /></ReactFlowProvider>;
}
