import type {ComponentHistory} from './component-types';

export function componentComparison(data:ComponentHistory, versionId:string) {
  const after=data.versions.find(version=>version.id===versionId);
  if(!after)return null;
  const before=data.versions.find(version=>version.id===after.parent_id) || after;
  const left=new Map(before.files.map(file=>[file.path,file]));
  const right=new Map(after.files.map(file=>[file.path,file]));
  const files=[...new Set([...left.keys(),...right.keys()])].sort().map(path=>{
    const a=left.get(path),b=right.get(path);
    return {path,before:a?.diff ?? null,after:b?.diff ?? null,
      recordedPatch:!!b && b.change!=='snapshot',
      status:!a?'Added':!b?'Removed':a.diff===b.diff?'Unchanged':'Modified'};
  });
  return {before,after,files};
}
/** Exact common edges make the changed block visible without guessing missing context. */
export function changedLines(before:string|null,after:string|null) {
  const a=before?.split('\n') || [],b=after?.split('\n') || [];
  let start=0,end=0;
  while(start<a.length && start<b.length && a[start]===b[start])start++;
  while(end<a.length-start && end<b.length-start && a[a.length-end-1]===b[b.length-end-1])end++;
  return {before:a.map((text,index)=>({text,changed:index>=start && index<a.length-end})),
    after:b.map((text,index)=>({text,changed:index>=start && index<b.length-end}))};
}
