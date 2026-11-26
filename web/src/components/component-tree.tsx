"use client";
import { memo, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import {
  ReactFlow, ReactFlowProvider, Handle, Position, ViewportPortal,
  getBezierPath,
  type EdgeProps, type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { type LineageBranch, type LineagePoint } from "@/lib/component-graph";
import { roundPageGraph } from "@/lib/component-round-page";
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
        aria-label={`${data.componentName} ${data.label}, ${data.caption || (data.stage === "experiment" ? "Candidate" : data.stage === "input" && !data.root && !data.contextName ? "Retained version" : "Starting version")}, round ${data.round}`}
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
  configuration?: Record<string, string>;
  selectedRound: number;
};

function LineageCanvas({data,step,selected,configuration,selectedRound,onSelect}:Props) {
  const host=useRef<HTMLDivElement>(null);
  const [width,setWidth]=useState(820);
  useEffect(()=>{
    if(!host.current)return;
    const observer=new ResizeObserver(([entry])=>setWidth(entry.contentRect.width));
    observer.observe(host.current);
    return ()=>observer.disconnect();
  },[]);
  const graph=useMemo(()=>roundPageGraph(data,selectedRound,step,width),[data,selectedRound,step,width]);
  const nodes=useMemo(()=>graph.nodes.map(node=>({...node,className:`${node.data.versionId===selected?'is-inspected':''} ${configuration?.[node.data.componentId]===node.data.versionId?'is-member':''}`})),[graph.nodes,selected,configuration]);
  const changed=new Set(graph.page.round ? roundChanges(data,graph.page.round,graph.page.step).filter(change=>change.generated.length).map(change=>change.component.id) : []);
  return <div ref={host} className="ce-round-canvas-scroll" role="region" aria-label={`Component lineage for ${selectedRound ? `round ${selectedRound}` : 'baseline'}`}>
    <div className="ce-page-stages" style={{width:graph.width}} aria-hidden="true">{graph.stages.map((stage,index)=><span key={stage.label} style={{left:stage.x}} className={index===graph.stages.length-1 && index>0 ? 'is-last' : ''}>{stage.label}</span>)}</div>
    <div className="ce-flow-host ce-uniform-lanes ce-round-page-canvas" data-recorded-step={graph.page.step} data-linked-round={selectedRound} style={{width:graph.width,height:graph.height,'--ce-canvas-zoom':1} as CSSProperties}>
      <ReactFlow<LineagePoint,LineageBranch>
        id="component-lineage" nodes={nodes} edges={graph.edges} nodeTypes={nodeTypes} edgeTypes={edgeTypes}
        nodeOrigin={[0.5,0.5]} defaultViewport={{x:0,y:0,zoom:1}}
        nodesDraggable={false} nodesConnectable={false} elementsSelectable={false} edgesFocusable={false}
        minZoom={1} maxZoom={1} zoomOnScroll={false} zoomOnPinch={false} zoomOnDoubleClick={false}
        panOnScroll={false} panOnDrag={false} preventScrolling={false}
        onNodeClick={(_,node)=>onSelect(node.data.versionId)}>
        <ViewportPortal>
          <svg className="ce-flow-backdrop" width={graph.width} height={graph.height} aria-hidden="true">{data.components.map((component,index)=>{
            const row=graph.rows.get(component.id)!;
            const color=COMPONENT_COLORS[index%COMPONENT_COLORS.length];
            return <g key={component.id}><rect x={4} y={row.top} width={graph.width-8} height={row.height} rx={8} fill="#fff" stroke={changed.has(component.id)?color:'#e7e7eb'} strokeOpacity={changed.has(component.id)?.55:1}/><rect x={4} y={row.top+12} width={3} height={row.height-24} rx={1.5} fill={color} opacity={.65}/></g>;
          })}</svg>
          {data.components.map((component,index)=><button key={component.id} className="ce-lane-heading nopan nodrag" style={{left:18,top:graph.rows.get(component.id)!.top+10,color:COMPONENT_COLORS[index%COMPONENT_COLORS.length]}} onClick={()=>onSelect(configuration?.[component.id] || graph.page.round?.start?.components[component.id] || component.baseline_version_id)} aria-label={`Inspect ${component.name} in this round's snapshot`}><i/>{component.name}</button>)}
        </ViewportPortal>
      </ReactFlow>
    </div>
  </div>;
}
export default function ComponentTree(props:Props) {
  return <ReactFlowProvider key={props.data.id}><LineageCanvas {...props}/></ReactFlowProvider>;
}
