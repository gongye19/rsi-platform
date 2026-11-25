"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, ArrowUpRight, Check, ChevronDown, FlaskConical, Loader2, Plus, RefreshCw, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import "./experiments.css";

type Metrics = { pass_at_1?: number; trial_success_count?: number; trial_count?: number; task_count?: number };
type TestResult = { metrics: Metrics; repeats?: number; reused_initial?: boolean };
type Policy = { allowed: string[]; denied: string[]; experimental_fields: string[] };
type Model = { model?: string; managed_by?: string };
type Config = { benchmark: string; models?: {execution?: Model; analysis?: Model}; components: Policy; parameters: Record<string, number>; initial_harness: string; full_evaluation: boolean };
type Run = { id: string; state: string; error: string; attempt: number; read_only: number; stage?: string; selected_version?: string; baseline_metrics: Metrics; tests: {initial?: TestResult; selected?: TestResult}; budget: {used?: number; total?: number}; configuration: Config; iteration_history: {iteration: number; candidate_version: string; review_decision: string; review_rationale: string; rollout_metrics?: Metrics; evaluation_mode?: string}[] };
type Artifact = {root: number; path: string; bytes: number};
type Options = {models: {id: string; label: string; model: string; configured: boolean}[]; components: {id: string; name: string}[]; proposal_only: string[]; experimental_fields: string[]; parameters: {key: string; label: string; default: number; min: number; max: number}[]};
type Preview = Config & { model_selection: {execution: string; analysis: string}; readiness: string; business_agent: boolean; mode: string };
const states: Record<string, string> = {draft: "草稿", queued: "排队中", running: "运行中", stopping: "停止中", stopped: "已停止", failed: "失败", interrupted: "已中断", succeeded: "已完成"};
const primary = new Set(["HAI_TOTAL_CREATION_BUDGET", "HAI_TRAIN_ROLLOUT_REPEATS", "HAI_TEST_ROLLOUT_REPEATS", "HAI_MAX_ROLLOUT_CONCURRENCY", "HAI_MAX_ANALYSIS_CONCURRENCY", "HAI_PROVIDER_MAX_CONCURRENCY"]);
function metric(m?: Metrics) {
  if (m?.pass_at_1 == null) return "—";
  return `${(m.pass_at_1 * 100).toFixed(1)}%${m.trial_count != null ? ` · ${m.trial_success_count ?? "?"}/${m.trial_count}` : ""}`;
}
async function read<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {cache: "no-store", ...init});
  const value = await response.json();
  if (!response.ok) throw new Error(value.error || "读取失败");
  return value;
}
export default function Experiments() {
  const [runs, setRuns] = useState<Run[]>([]);
  const [profiles, setProfiles] = useState<string[]>([]);
  const [options, setOptions] = useState<Options | null>(null);
  const [profile, setProfile] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [models, setModels] = useState({execution: "", analysis: ""});
  const [policy, setPolicy] = useState<Policy>({allowed: [], denied: [], experimental_fields: []});
  const [parameters, setParameters] = useState<Record<string, number>>({});
  const [initial, setInitial] = useState("");
  const [full, setFull] = useState(true);
  const [id, setId] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [detail, setDetail] = useState<{status: Run; events: unknown; files: Artifact[]} | null>(null);
  const [content, setContent] = useState("");
  const refresh = useCallback(async (signal?: AbortSignal) => {
    try { setRuns(await read<Run[]>("/api/platform", {signal})); }
    catch (e) { if (!signal?.aborted) setError((e as Error).message); }
  }, []);
  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([read<string[]>("/api/platform?profiles=1", {signal: abort.signal}), read<Options>("/api/platform?options=1", {signal: abort.signal})])
      .then(([p, o]) => {setProfiles(p); setOptions(o); setProfile(p.includes("crm-local.toml") ? "crm-local.toml" : p[0] || "");})
      .catch(e => {if (!abort.signal.aborted) setError((e as Error).message);});
    const first = setTimeout(() => void refresh(abort.signal), 0);
    const timer = setInterval(() => void refresh(abort.signal), 5000);
    return () => {abort.abort(); clearTimeout(first); clearInterval(timer);};
  }, [refresh]);
  useEffect(() => {
    if (!profile) return;
    const abort = new AbortController();
    void read<Preview>("/api/platform?" + new URLSearchParams({profiles: "1", name: profile}), {signal: abort.signal})
      .then(value => {setPreview(value); setModels(value.model_selection); setPolicy(value.components); setParameters(value.parameters); setInitial(value.initial_harness); setFull(value.full_evaluation);})
      .catch(e => {if (!abort.signal.aborted) setError((e as Error).message);});
    return () => abort.abort();
  }, [profile]);
  async function act(action: string, run?: string) {
    setBusy(true); setError(""); setNotice("");
    try {
      const result = await read<Run>("/api/platform", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action, run_id: run || id, profile, settings: {models, components: policy, parameters, initial_harness: initial, full_evaluation: full}})});
      setNotice(action === "create" ? `已保存 ${result.id} 的独立配置；点击列表中的「启动」开始实验。` : `${result.id}：${states[result.state] || result.state}`);
      await refresh();
      if (action === "create") {setId(""); await inspect(result.id);}
    } catch (e) {setError((e as Error).message);} finally {setBusy(false);}
  }
  async function inspect(run: string) {
    try {
      const query = "/api/platform?" + new URLSearchParams({run});
      const [status, events, files] = await Promise.all([read<Run>(query), read<unknown>(query + "&events=1"), read<Artifact[]>(query + "&artifacts=1")]);
      setDetail({status, events, files}); setContent("");
    } catch (e) {setError((e as Error).message);}
  }
  async function openFile(file: Artifact) {
    if (!detail) return;
    try {setContent((await read<{content: string}>("/api/platform?" + new URLSearchParams({run: detail.status.id, root: String(file.root), path: file.path}))).content);}
    catch (e) {setError((e as Error).message);}
  }
  return <main className="experiments-page">
    <header className="experiment-header"><div><Link className="experiment-back" href="/"><ArrowLeft size={13}/>自进化谱系</Link><h1><FlaskConical size={24}/>实验管理</h1><p>配置组件与模型，启动实验，查看每一轮的真实记录。</p></div><span className="experiment-runtime">OpenCode · 1.18.32</span></header>
    {error && <p className="experiment-error" role="alert">{error}</p>}{notice && <p className="experiment-notice" role="status"><Check size={15}/>{notice}</p>}
    <form className="experiment-card" onSubmit={e => {e.preventDefault(); void act("create");}}>
      <div className="experiment-section-title"><h2><Settings2 size={17}/>创建实验</h2><span>创建仅保存配置，启动后调用真实模型</span></div>
      <div className="experiment-grid experiment-basics">
        <label className="experiment-field">启动配置<select required value={profile} onChange={e => {setProfile(e.target.value); setPreview(null);}}><option value="" disabled>加载配置…</option>{profiles.map(p => <option key={p}>{p}</option>)}</select></label>
        <label className="experiment-field">实验编号 <span className="field-hint">可留空自动生成</span><Input value={id} onChange={e => setId(e.target.value)} placeholder="例如 crm-evolution-03" pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,90}" maxLength={91}/></label>
      </div>
      {preview && options ? <>
        <div className="experiment-context"><span>Benchmark <strong>{preview.benchmark}</strong></span><span>{preview.business_agent ? "业务 HTTP / Python 接入" : "本机原生执行"}</span>{preview.readiness !== "ready" && <span className="experiment-warning">接入草稿 · 完成业务配置后才可启动</span>}</div>
        <div className="experiment-grid experiment-models">{(["execution", "analysis"] as const).map(role => <label className="experiment-field" key={role}>{role === "execution" ? "执行模型" : "分析模型"}<select required aria-label={role === "execution" ? "执行模型" : "分析模型"} disabled={role === "execution" && preview.business_agent} value={models[role]} onChange={e => setModels({...models, [role]: e.target.value})}>
          {role === "execution" && preview.business_agent ? <option value="business_agent">由业务 Agent 服务配置</option> : <><option value="" disabled>请选择模型</option>{options.models.map(m => <option value={m.id} key={m.id} disabled={!m.configured}>{m.label}{!m.configured ? " · 缺少密钥" : ""}</option>)}</>}
        </select><span className="field-hint">{role === "execution" ? "负责解答 benchmark 的业务问题" : "负责发现、归因、生成修改与采用评审；评分器另按 benchmark 配置"}</span></label>)}</div>
        <div className="experiment-component-title"><h3>可优化组件 <span>{policy.allowed.length} / {options.components.length}</span></h3><div><Button type="button" variant="ghost" size="sm" onClick={() => setPolicy({...policy, allowed: options.components.map(c => c.id), denied: []})}>全选</Button><Button type="button" variant="ghost" size="sm" onClick={() => setPolicy({...policy, allowed: [], denied: options.components.map(c => c.id)})}>清空</Button></div></div>
        <p className="experiment-help">勾选表示允许修改。模型仍会结合任务和运行能力发现可用组件，候选必须通过实际加载检查。</p>
        <div className="experiment-components">{options.components.map((c, index) => <label key={c.id} className={policy.allowed.includes(c.id) ? "component-choice selected" : "component-choice"}><input type="checkbox" checked={policy.allowed.includes(c.id)} onChange={() => {const allowed = policy.allowed.includes(c.id) ? policy.allowed.filter(x => x !== c.id) : [...policy.allowed, c.id]; setPolicy({...policy, allowed, denied: options.components.filter(x => !allowed.includes(x.id)).map(x => x.id)});}}/><span className="component-number">{String(index + 1).padStart(2, "0")}</span>{c.name}</label>)}</div>
        <p className="experiment-help">原有 5 类仅可建议项保持只读，不进入可修改范围。{policy.allowed.length === 0 && <strong> 当前未开放组件，只能评测初始版本。</strong>}</p>
        <h3 className="experiment-subtitle">进化参数</h3><div className="experiment-grid experiment-parameters">{options.parameters.filter(p => primary.has(p.key)).map(p => <label className="experiment-field" key={p.key}>{p.label}<Input type="number" required min={p.min} max={p.max} step={1} value={parameters[p.key] ?? p.default} onChange={e => setParameters({...parameters, [p.key]: Number(e.target.value)})}/></label>)}</div>
        <details className="experiment-advanced"><summary><ChevronDown size={14}/>更多设置 · 超时、重试与初始 Harness</summary>
          <div className="experiment-grid experiment-parameters">{options.parameters.filter(p => !primary.has(p.key) && (!preview.business_agent || p.key !== "HAI_CRM_TIMEOUT_S")).map(p => <label className="experiment-field" key={p.key}>{p.label}<Input type="number" required min={p.min} max={p.max} step={1} value={parameters[p.key] ?? p.default} onChange={e => setParameters({...parameters, [p.key]: Number(e.target.value)})}/></label>)}</div>
          <label className="experiment-field">初始 Harness <span className="field-hint">服务器上的目录或导出包路径；留空使用空 Harness</span><Input value={initial} onChange={e => setInitial(e.target.value)} placeholder="/path/to/business-harness"/></label>
          {policy.allowed.includes("experimental_policies") && <fieldset className="experimental-fields"><legend>明确允许的实验性行为字段</legend>{options.experimental_fields.map(field => <label key={field}><input type="checkbox" checked={policy.experimental_fields.includes(field)} onChange={() => setPolicy({...policy, experimental_fields: policy.experimental_fields.includes(field) ? policy.experimental_fields.filter(x => x !== field) : [...policy.experimental_fields, field]})}/>{field}</label>)}</fieldset>}
          <details className="experiment-readonly"><summary>查看 5 类仅可建议项</summary><p>{options.proposal_only.join(" · ")}</p></details>
        </details>
        <footer className="experiment-form-footer"><label className="experiment-check"><input type="checkbox" checked={full} disabled={preview.mode !== "train"} onChange={e => setFull(e.target.checked)}/>训练后冻结版本并执行 TEST</label><Button type="submit" disabled={busy || !models.execution || !models.analysis}>{busy ? <Loader2 className="animate-spin" size={15}/> : <Plus size={15}/>}创建实验</Button></footer>
      </> : <p className="experiment-help experiment-loading"><Loader2 className="animate-spin" size={15}/>正在读取服务器的模型与默认配置…</p>}
    </form>
    <section className="experiment-card experiment-runs"><div className="experiment-section-title"><h2>实验记录 <span>{runs.length}</span></h2><Button variant="ghost" size="sm" onClick={() => void refresh()}><RefreshCw size={14}/>刷新</Button></div>
      <div className="experiment-table-wrap"><table><thead><tr>{["实验 / 冻结版本", "状态", "TRAIN 基线", "TEST 初始 → 最终", "会话预算", "操作"].map(t => <th key={t}>{t}</th>)}</tr></thead><tbody>{runs.map(run => <tr key={run.id}><td><button type="button" className="experiment-run-link" onClick={() => void inspect(run.id)}>{run.id}</button><small>{run.read_only ? "原 CLI 实验 · 只读" : `尝试 ${run.attempt} 次`}{run.selected_version ? ` · ${run.selected_version}` : ""}</small></td><td><span className={`experiment-state state-${run.state}`}>{states[run.state] || run.state}</span>{run.state === "running" && run.stage && <small>{run.stage}</small>}</td><td>{metric(run.baseline_metrics)}</td><td>{run.tests?.initial ? <>{metric(run.tests.initial.metrics)}<small>→ {metric(run.tests.selected?.metrics)}{run.tests.selected?.reused_initial ? "（同一 v0，复用结果）" : ""}</small></> : "—"}</td><td>{run.budget?.total != null ? `${run.budget.used} / ${run.budget.total}` : "—"}</td><td><div className="experiment-actions"><Button size="sm" variant="ghost" onClick={() => void inspect(run.id)}>详情</Button><Link className="experiment-tree-link" href={`/?run=${run.id}`} aria-label={`${run.id} 谱系`}>谱系<ArrowUpRight size={12}/></Link>{!run.read_only && <>
        {run.state === "draft" && <Button size="sm" disabled={busy} onClick={() => void act("start", run.id)}>启动</Button>}
        {["queued", "running", "stopping"].includes(run.state) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act("stop", run.id)}>停止</Button>}
        {["stopped", "failed", "interrupted"].includes(run.state) && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act("resume", run.id)}>恢复</Button>}
      </>}</div></td></tr>)}</tbody></table>{runs.length === 0 && <p className="experiment-empty">暂无实验。保存配置后，可在这里启动并查看进度。</p>}</div>
    </section>
    {detail && <section className="experiment-card experiment-detail" aria-label="实验详情"><div className="experiment-section-title"><h2>{detail.status.id}</h2><Button size="sm" variant="ghost" onClick={() => void inspect(detail.status.id)}>刷新详情</Button></div>
      <div className="experiment-summary"><div><span>最终版本</span><strong>{detail.status.selected_version || "尚未冻结"}</strong></div><div><span>TRAIN 初始成绩</span><strong>{metric(detail.status.baseline_metrics)}</strong></div><div><span>TEST 最终成绩</span><strong>{metric(detail.status.tests?.selected?.metrics)}</strong><small>每题 {detail.status.tests?.selected?.repeats ?? "—"} 次</small></div></div>
      {detail.status.error && <p className="experiment-error">{detail.status.error}</p>}
      {detail.status.iteration_history?.map(round => <div className="experiment-review" key={round.iteration}><strong>第 {round.iteration} 轮 · {round.candidate_version}</strong><span>{round.review_decision}</span><p>{round.review_rationale}</p><small>{round.evaluation_mode === "channel_preflight" ? "组件预检阶段" : `候选 TRAIN：${metric(round.rollout_metrics)} · ${round.rollout_metrics?.task_count ?? "—"} 题`}</small></div>)}
      <details><summary>本次保存的配置</summary><pre>{JSON.stringify(detail.status.configuration, null, 2)}</pre></details>
      <details><summary>状态、预算与事件</summary><pre>{JSON.stringify({state: detail.status.state, budget: detail.status.budget, events: detail.events}, null, 2)}</pre></details>
      <label className="experiment-field">原始记录与产物<select defaultValue="" key={detail.status.id} onChange={e => {const file = detail.files[Number(e.target.value)]; if (file) void openFile(file);}}><option value="" disabled>选择日志、trace、答案或评测结果</option>{detail.files.map((file, index) => <option key={`${file.root}:${file.path}`} value={index}>{file.root}/{file.path} ({file.bytes} B)</option>)}</select></label>{content && <pre className="experiment-artifact">{content}</pre>}
    </section>}
    <p className="experiment-footnote">所有配置、日志、trace 和版本保存在实验平台侧。历史记录只读导入，查看不会重新运行模型。</p>
  </main>;
}
