"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";

type Run = { id: string; state: string; error: string; attempt: number };
type File = {root: number; path: string; bytes: number};
type Model = {model?: string; api?: string; base_url?: string; base_url_env?: string; managed_by?: string};
export default function Experiments() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [profile, setProfile] = useState("");
  const [models, setModels] = useState<{execution?: Model; analysis?: Model} | null>(null);
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<{id: string; status: unknown; events: unknown; files: File[]} | null>(null);
  const [content, setContent] = useState("");
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try {
      const [r, p] = await Promise.all([fetch("/api/platform", { signal }), fetch("/api/platform?profiles=1", { signal })]);
      const [a, b] = await Promise.all([r.json(), p.json()]);
      if (!r.ok || !p.ok) throw new Error(a.error || b.error || "读取失败");
      setRuns(a); setProfiles(b); setError("");
    } catch (e) { if (!signal?.aborted) setError((e as Error).message); }
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    const first = setTimeout(() => void refresh(abort.signal), 0);
    const timer = setInterval(() => void refresh(abort.signal), 3000);
    return () => { abort.abort(); clearTimeout(first); clearInterval(timer); };
  }, [refresh]);
  useEffect(() => {
    if (!profile) return;
    const abort = new AbortController();
    void fetch("/api/platform?" + new URLSearchParams({profiles: "1", name: profile}), {signal: abort.signal})
      .then(async response => { const value = await response.json(); if (!response.ok) throw new Error(value.error); return value; })
      .then(value => setModels(value.models))
      .catch(e => { if (!abort.signal.aborted) setError((e as Error).message); });
    return () => abort.abort();
  }, [profile]);
  async function act(action: string, run?: string) {
    setBusy(true); setError("");
    try {
      const response = await fetch("/api/platform", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, run_id: run || id, profile }) });
      const data = await response.json();
      if (!response.ok) throw new Error(data.error || "操作失败");
      await refresh();
    } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }
  async function inspect(run: string) {
    try {
      const responses = await Promise.all(["", "&events=1", "&artifacts=1"].map(suffix => fetch(`/api/platform?run=${run}${suffix}`)));
      const [status, events, files] = await Promise.all(responses.map(response => response.json()));
      if (responses.some(response => !response.ok)) throw new Error("读取实验记录失败");
      setDetail({id: run, status, events, files}); setContent("");
    } catch (e) { setError((e as Error).message); }
  }
  async function openFile(file: File) {
    if (!detail) return;
    try {
      const response = await fetch("/api/platform?" + new URLSearchParams({run: detail.id, root: String(file.root), path: file.path}));
      const result = await response.json();
      if (!response.ok) throw new Error(result.error || "读取失败");
      setContent(result.content);
    } catch (e) { setError((e as Error).message); }
  }
  return <main style={{ maxWidth: 1100, margin: "40px auto", padding: 24 }}>
    <Link href="/">← 自进化谱系</Link><h1 style={{ fontSize: 28, margin: "20px 0" }}>实验管理</h1>
    <p>创建实验不调用模型；启动或恢复会使用配置的真实模型和业务服务。草稿配置不可启动。</p>
    <form onSubmit={e => { e.preventDefault(); void act("create"); }} style={{ display: "flex", gap: 12, flexWrap: "wrap", margin: "24px 0" }}>
      <label>配置 <select required value={profile} onChange={e => {setProfile(e.target.value); setModels(null);}}><option value="" disabled>请选择启动配置</option>{profiles.map(p => <option key={p}>{p}</option>)}</select></label>
      <label>实验编号 <input value={id} onChange={e => setId(e.target.value)} placeholder="可留空自动生成" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,95}" /></label>
      <button disabled={busy || !profile || !models?.execution || !models?.analysis} type="submit">创建实验</button>
    </form>
    {profile && models ? <p>执行：{models.execution?.managed_by === "business_agent" ? "由业务服务管理" : `${models.execution?.model || "未指定"} · ${models.execution?.api || ""}`}<br />
      分析：{models.analysis?.model || "未指定"} · {models.analysis?.api || ""}<br />
      两组模型在所选 TOML 的 models.execution / models.analysis 中配置；密钥保存在服务端。缺少配置将阻止启动。</p> : null}
    {error ? <p role="alert" style={{ color: "#b42318" }}>{error}</p> : null}
    <table style={{ width: "100%", borderCollapse: "collapse" }}><thead><tr>{["实验", "状态", "尝试", "操作"].map(t => <th key={t} style={{ textAlign: "left", padding: 10 }}>{t}</th>)}</tr></thead>
      <tbody>{runs.map(run => <tr key={run.id} style={{ borderTop: "1px solid #ddd" }}>
        <td style={{ padding: 10 }}><a href={`/?run=${run.id}`}>{run.id}</a>{run.error ? <p>{run.error}</p> : null}</td>
        <td>{run.state}</td><td>{run.attempt}</td><td style={{ display: "flex", gap: 12, padding: 10 }}>
          <button onClick={() => void inspect(run.id)}>查看记录</button>
          {run.state === "draft" ? <button disabled={busy} onClick={() => void act("start", run.id)}>启动</button> : null}
          {["queued", "running", "stopping"].includes(run.state) ? <button disabled={busy} onClick={() => void act("stop", run.id)}>停止</button> : null}
          {["stopped", "failed", "interrupted"].includes(run.state) ? <button disabled={busy} onClick={() => void act("resume", run.id)}>恢复</button> : null}
        </td>
      </tr>)}</tbody></table>
    {detail ? <section style={{marginTop: 32}}><h2>实验记录 · {detail.id}</h2>
      <button onClick={() => void inspect(detail.id)}>刷新记录</button>
      <details><summary>状态与预算</summary><pre style={{whiteSpace: "pre-wrap"}}>{JSON.stringify(detail.status, null, 2)}</pre></details>
      <details><summary>最近事件（前 500 条；完整分页可用 API）</summary><pre style={{whiteSpace: "pre-wrap"}}>{JSON.stringify(detail.events, null, 2)}</pre></details>
      <label>产物 <select defaultValue="" key={detail.id} onChange={e => { const file = detail.files[Number(e.target.value)]; if (file) void openFile(file); }}>
        <option value="" disabled>选择日志、trace、答案或配置</option>
        {detail.files.map((file, index) => <option key={`${file.root}:${file.path}`} value={index}>{file.root}/{file.path} ({file.bytes} B)</option>)}
      </select></label><pre style={{whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 600, overflow: "auto"}}>{content}</pre>
    </section> : null}
  </main>;
}
