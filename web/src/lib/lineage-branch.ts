export type BranchPoint={x:number;y:number};
/** Siblings leave the same short trunk, reach their rails together, then run horizontally. */
export function lineageBranchPath(source:BranchPoint,target:BranchPoint,nearestTargetX=target.x) {
  if(Math.abs(source.y-target.y)<.01)return `M ${source.x} ${source.y} L ${target.x} ${target.y}`;
  const gap=Math.max(0,Math.min(target.x,nearestTargetX)-source.x);
  const start=source.x+Math.min(52,gap/4);
  const end=source.x+Math.min(132,gap*.7);
  const control=(end-start)*.4;
  return `M ${source.x} ${source.y} L ${start} ${source.y} C ${start+control} ${source.y}, ${end-control} ${target.y}, ${end} ${target.y} L ${target.x} ${target.y}`;
}
