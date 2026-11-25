"use client";
import { useEffect, useRef, type ReactNode } from "react";
import { useGroupRef } from "react-resizable-panels";
import { ResizableHandle, ResizablePanel, ResizablePanelGroup } from "@/components/ui/resizable";
import { preferredLineagePercent } from "@/lib/presentation";

const initialLayout = { lineage: 60, results: 40 };
export default function EvolutionWorkspace({ left, right }: { left: ReactNode; right: ReactNode }) {
  const host = useRef<HTMLDivElement>(null);
  const group = useGroupRef();
  const width = useRef(1280);
  const preference = useRef<number | null>(null);
  useEffect(() => {
    if (!host.current) return;
    let frame = 0;
    const observer = new ResizeObserver(([entry]) => {
      width.current = entry.contentRect.width;
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const left = preference.current ?? preferredLineagePercent(width.current);
        group.current?.setLayout({ lineage: left, results: 100 - left });
      });
    });
    observer.observe(host.current);
    return () => { observer.disconnect(); cancelAnimationFrame(frame); };
  }, [group]);
  return <div ref={host} className="ce-workspace-scroll">
    <ResizablePanelGroup orientation="horizontal" className="ce-dual" groupRef={group} defaultLayout={initialLayout}
      onLayoutChanged={(layout, meta) => { if (meta.isUserInteraction) preference.current = layout.lineage; }}>
      <ResizablePanel id="lineage" defaultSize="60%" minSize="520px" maxSize="72%">{left}</ResizablePanel>
      <ResizableHandle withHandle aria-label="Resize lineage and results" title="Drag to resize. Double-click to reset." className="ce-split-handle"
        onDoubleClick={() => {
          preference.current = null;
          const left = preferredLineagePercent(width.current);
          group.current?.setLayout({ lineage: left, results: 100 - left });
        }} />
      <ResizablePanel id="results" defaultSize="40%" minSize="380px">{right}</ResizablePanel>
    </ResizablePanelGroup>
  </div>;
}
