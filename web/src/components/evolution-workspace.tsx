"use client";
import { type ReactNode } from "react";
import { useGroupRef } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";

const initialLayout = { lineage: 50, results: 50 };
export default function EvolutionWorkspace({ left, right }: { left: ReactNode; right: ReactNode }) {
  const group = useGroupRef();
  return <div className="ce-workspace-scroll">
    <ResizablePanelGroup orientation="horizontal" className="ce-dual" groupRef={group} defaultLayout={initialLayout}>
      <ResizablePanel id="lineage" defaultSize="50%" minSize="460px">{left}</ResizablePanel>
      <ResizableHandle withHandle aria-label="Resize lineage and results" title="Drag to resize. Double-click to reset to equal widths." className="ce-split-handle"
        onDoubleClick={() => group.current?.setLayout(initialLayout)} />
      <ResizablePanel id="results" defaultSize="50%" minSize="460px">{right}</ResizablePanel>
    </ResizablePanelGroup>
  </div>;
}
