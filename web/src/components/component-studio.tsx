"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  ChevronDown,
  Info,
  Code2,
  FileText,
  GitBranch,
  Pause,
  Play,
  RefreshCw,
  RotateCcw,
  Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Popover, PopoverTrigger, PopoverContent } from "@/components/ui/popover";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import ComponentTree from "./component-tree";
import RoundOutcomeChart from "./round-outcome-chart";
import EvolutionWorkspace from "./evolution-workspace";
import { harnessViews } from "@/lib/harness-views";
import { evolutionRounds } from "@/lib/component-layout";
import { advanceReplay } from "@/lib/replay";
import {
  activeAt,
  decisionAt,
  decisionLabels,
  type ComponentHistory,
} from "@/lib/component-types";
import type { Artifact } from "@/lib/types";
import "./component-studio.css";
async function request<T>(
  params: URLSearchParams,
  signal?: AbortSignal,
): Promise<T> {
  const r = await fetch("/api/evolution?" + params, {
    signal,
    cache: "no-store",
  });
  if (!r.ok) throw new Error("组件谱系暂时无法读取，请检查记录或重试。");
  return r.json();
}
export default function ComponentStudio() {
  const [source, setSource] = useState<"live" | "harnesslens">("live");
  const [run, setRun] = useState("");
  useEffect(() => {
    const first = setTimeout(() => {
      const identity = new URLSearchParams(window.location.search).get("run");
      if (identity) { setRun(identity); setSource("live"); }
    }, 0);
    return () => clearTimeout(first);
  }, []);
  const [task, setTask] = useState("FDA0015");
  const [data, setData] = useState<ComponentHistory | null>(null);
  const [cursor, setCursor] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [selected, setSelected] = useState("");
  const [hoveredRound, setHoveredRound] = useState<number | null>(null);
  const [focusedRound, setFocusedRound] = useState<number | null>(null);
  const [focusRevision, setFocusRevision] = useState(0);
  const [inspectedId, setInspectedId] = useState<string | null>(null);
  const [panel, setPanel] = useState(false);
  const [tab, setTab] = useState<"diff" | "trace" | "answer">("diff");
  const [artifact, setArtifact] = useState<
    (Artifact & { caption?: string }) | null
  >(null);
  const [artifactError, setArtifactError] = useState("");
  const requestEpoch = useRef(0);
  const refresh = useCallback(
    async (signal?: AbortSignal) => {
      const epoch = requestEpoch.current;
      try {
        const d = await request<ComponentHistory>(
          new URLSearchParams({ source, task, run }),
          signal,
        );
        if (!signal?.aborted && epoch === requestEpoch.current) {
          setData(d);
          setError("");
          setLoading(false);
        }
      } catch (e) {
        if (
          (e as Error).name !== "AbortError" &&
          epoch === requestEpoch.current
        ) {
          setError((e as Error).message);
          setLoading(false);
        }
      }
    },
    [source, task, run],
  );
  useEffect(() => {
    const abort = new AbortController();
    const first = setTimeout(() => void refresh(abort.signal), 0);
    const timer = setInterval(() => void refresh(abort.signal), 15000);
    return () => {
      abort.abort();
      clearTimeout(first);
      clearInterval(timer);
    };
  }, [refresh]);
  const max = (data?.steps.length || 1) - 1;
  const step = Math.min(Math.floor(cursor ?? max), max);
  const progress = cursor == null ? 1 : Math.min(1, Math.max(0, cursor - step));
  const playbackPosition = useRef(0);
  useEffect(() => {
    playbackPosition.current = cursor ?? max + 1;
  }, [cursor, max]);
  const event = data?.steps[step];
  const active = data ? activeAt(data, step) : undefined;
  const trial = data?.bundles.find((b) => b.id === event?.bundle_id);
  const views = useMemo(
    () => (data ? harnessViews(data, step) : []),
    [data, step],
  );
  const rounds = useMemo(() => (data ? evolutionRounds(data) : []), [data]);
  const round =
    rounds.find((r) => r.round === focusedRound && r.firstStep <= step) ||
    rounds.filter((r) => r.firstStep <= step).at(-1);
  const visibleHover =
    hoveredRound === 0 ||
    rounds.some((r) => r.round === hoveredRound && r.firstStep <= step)
      ? hoveredRound
      : null;
  const linkedRound =
    visibleHover ?? (focusedRound === 0 ? 0 : (round?.round ?? 0));
  const inspected =
    views.find((v) => v.id === inspectedId) ||
    views.find((v) => v.bundleIds.includes(active?.id || "")) ||
    views.at(-1);
  const inspectedBundle = inspected?.bundleIds.includes(active?.id || "")
    ? active
    : inspected?.bundle;
  function inspectHarness(id: string) {
    setInspectedId(id);
    setPlaying(false);
    setPanel(false);
  }

  const visibleVersions = useMemo(
    () => data?.versions.filter((v) => v.step <= step) || [],
    [data, step],
  );
  const version = visibleVersions.find((v) => v.id === selected);
  const versionId = version?.id;
  const component = data?.components.find(
    (c) => c.id === version?.component_id,
  );
  const decision =
    data && version ? decisionAt(data, version.id, step) : undefined;
  useEffect(() => {
    if (!playing || !data) return;
    let frame: number;
    let previous: number | undefined;
    const advance = (now: number) => {
      // A background tab pauses its presentation clock instead of skipping events.
      const delta = previous == null ? 0 : Math.min(100, now - previous);
      previous = now;
      const next = advanceReplay(data, playbackPosition.current, delta * speed);
      playbackPosition.current = next;
      setCursor(next);
      if (next >= data.steps.length) setPlaying(false);
      else frame = requestAnimationFrame(advance);
    };
    frame = requestAnimationFrame(advance);
    return () => cancelAnimationFrame(frame);
  }, [playing, data, speed]);
  useEffect(() => {
    if (!panel || !versionId || tab === "diff") return;
    const abort = new AbortController();
    request<Artifact & { caption?: string }>(
      new URLSearchParams({ source, task, run, version: versionId, kind: tab }),
      abort.signal,
    )
      .then(setArtifact)
      .catch((e) => {
        if (e.name !== "AbortError") setArtifactError(e.message);
      });
    return () => abort.abort();
  }, [source, task, run, panel, versionId, tab]);
  function reset(nextSource: "live" | "harnesslens", nextTask = task) {
    requestEpoch.current += 1;
    setSource(nextSource);
    setTask(nextTask);
    setData(null);
    setLoading(true);
    setCursor(null);
    setPlaying(false);
    setPanel(false);
    setSelected("");
    setInspectedId(null);
    setFocusedRound(null);
    setHoveredRound(null);
    setArtifact(null);
    setArtifactError("");
  }
  const choose = useCallback((id: string) => {
    setPlaying(false);
    setSelected(id);
    setPanel(true);
    setTab("diff");
    setArtifact(null);
    setArtifactError("");
  }, []);
  const focusRound = useCallback((r: number) => {
    setFocusedRound(r);
    setFocusRevision((value) => value + 1);
    setHoveredRound(null);
    setPlaying(false);
  }, []);
  return (
    <div className={`ce-root ${cursor == null ? "ce-follow-live" : "ce-replaying"}`}>
      <main className="ce-experiment">
        <div className="ce-controls">
          <Select value={source} onValueChange={(value) => reset(value as "live" | "harnesslens")}>
            <SelectTrigger aria-label="数据来源"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="harnesslens">HarnessLens · 示例</SelectItem>
              <SelectItem value="live">接入实验</SelectItem>
            </SelectContent>
          </Select>
          {source === "live" && !!data?.tasks?.length && (
            <Select value={task} onValueChange={(value) => reset(source, value)}>
              <SelectTrigger className="ce-task-picker" aria-label="选择实验任务"><SelectValue /></SelectTrigger>
              <SelectContent>
                {data.tasks.map((t) => <SelectItem key={t.id} value={t.id}>{t.id} · {t.domain.replaceAll("_", " ")}</SelectItem>)}
              </SelectContent>
            </Select>
          )}
          <span className="ce-method-label">{data?.algorithm}{data?.profile?.version ? ` · ${data.profile.runtime} ${data.profile.version}` : ""}</span>
          <div className="ce-harness-picker">
            <a href="/experiments">实验管理</a>
            <span>Harness</span>
            <Select value={inspected?.id || ""} onValueChange={inspectHarness} disabled={!views.length}>
              <SelectTrigger aria-label="选择完整Harness"><SelectValue placeholder="—" /></SelectTrigger>
              <SelectContent>
                {views.map((v) => <SelectItem key={v.id} value={v.id}>{v.label}{v.bundleIds.includes(active?.id || "") ? " · 生效" : ""}</SelectItem>)}
              </SelectContent>
            </Select>
          </div>
          {data?.source === "example" && (
            <span className="ce-demo-tag">示例数据</span>
          )}
          <Popover>
            <PopoverTrigger asChild><Button variant="ghost" size="icon-sm" aria-label="实验记录说明"><Info size={14} /></Button></PopoverTrigger>
            <PopoverContent align="end" className="ce-record-popover">
              <p>{data?.notice || "只读实验记录"}</p>
              <p>评分、耗时和 Token 使用各自的纵轴刻度，纵轴可从非零值开始。沿用配置时，展示已有测量。</p>
            </PopoverContent>
          </Popover>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="刷新谱系"
            onClick={() => void refresh()}
          >
            <RefreshCw size={14} />
          </Button>
        </div>
        <div className="ce-experiment-legend">
          <span>
            <i className="ce-key-normal" /> 正常节点
          </span>
          <span>
            <i className="ce-key-rejected">×</i> 未采用
          </span>
          <span>
            <i className="ce-key-trunk" /> 版本派生
          </span>
          <span>
            <i className="ce-key-carry" /> 版本沿用
          </span>
        </div>
        {error && (
          <div className="ce-error" role="alert">
            {error}
            <Button variant="ghost" size="sm" onClick={() => void refresh()}>
              重新读取
            </Button>
          </div>
        )}
        {loading && !data ? (
          <div className="ce-loading">
            <GitBranch size={24} />
            加载中…
          </div>
        ) : (
          data && (
            <>
              <EvolutionWorkspace left={
                    <section className="ce-lineages">
                      <div className="ce-result-heading"><h2 className="ce-plot-title">
                        组件谱系 <span className="ce-component-count">{data.components.length}</span>
                      </h2><span className="ce-round-chip"><i />{linkedRound === 0 ? "初始" : `第 ${linkedRound} 轮`}</span></div>
                      <div
                        className="ce-tree-scroll"
                        tabIndex={0}
                        role="region"
                        aria-label="组件谱系，可横向滚动"
                      >
                        <ComponentTree
                          data={data}
                          step={step}
                          progress={progress}
                          selected={selected}
                          configuration={inspectedBundle?.components}
                          selectedRound={linkedRound}
                          focusedRound={focusedRound}
                          focusRevision={focusRevision}
                          onHoverRound={setHoveredRound}
                          onRound={focusRound}
                          playing={playing}
                          onSelect={choose}
                        />
                      </div>
                    </section>
                  } right={
                    <section className="ce-results">
                      <div className="ce-result-heading">
                        <h2 className="ce-plot-title">整体结果</h2>
                        <span className="ce-round-chip"><i />{linkedRound === 0 ? "初始" : `第 ${linkedRound} 轮`}</span>
                      </div>
                      <RoundOutcomeChart
                        data={data}
                        step={step}
                        playing={playing}
                        activeRound={linkedRound}
                        onHoverRound={setHoveredRound}
                        onRound={focusRound}
                      />
                    </section>
                  } />
              <div className="ce-bottom">
                <div
                  className="ce-event"
                  title={
                    trial
                      ? `试跑记录：${trial.label}；实际生效：${active?.label}`
                      : undefined
                  }
                >
                  {event?.label}
                </div>
                <section className="ce-replay" aria-label="事件回放">
                  <Button
                    size="icon"
                    className="ce-play"
                    aria-label={playing ? "暂停回放" : "播放回放"}
                    onClick={() => {
                      if (playing) setPlaying(false);
                      else {
                        if (step === max && progress >= 1) setCursor(0);
                        setPanel(false);
                        setInspectedId(null);
                        setFocusedRound(null);
                        setHoveredRound(null);
                        setPlaying(true);
                      }
                    }}
                  >
                    {playing ? <Pause size={15} /> : <Play size={15} />}
                  </Button>
                  <div className="ce-replay-track">
                    <div>
                      <strong>
                        {event?.round ? `第 ${event.round} 轮 · ` : ""}步骤 {step} / {max}
                      </strong>
                    </div>
                    <Slider
                      aria-label="回放步骤"
                      min={0}
                      max={max + 1}
                      step={0.001}
                      value={[cursor ?? max + 1]}
                      onValueChange={([value]) => {
                        setPlaying(false);
                        setCursor(value);
                        setFocusedRound(null);
                        setHoveredRound(null);
                        setInspectedId(null);
                        setPanel(false);
                      }}
                    />
                  </div>
                  <Select value={String(speed)} onValueChange={(value) => setSpeed(Number(value))}>
                    <SelectTrigger className="ce-speed-picker" aria-label="回放速度"><SelectValue /></SelectTrigger>
                    <SelectContent side="top">
                      {[0.5, 1, 2].map((value) => <SelectItem key={value} value={String(value)}>{value}×</SelectItem>)}
                    </SelectContent>
                  </Select>
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    aria-label="显示全部版本"
                    onClick={() => {
                      setPlaying(false);
                      setCursor(null);
                      setFocusedRound(null);
                      setHoveredRound(null);
                      setInspectedId(null);
                    }}
                  >
                    <RotateCcw size={13} />
                  </Button>
                </section>
              </div>
            </>
          )
        )}
      </main>
      <Sheet open={panel && !!version} onOpenChange={setPanel}>
        <SheetContent className="ce-evidence">
          <SheetHeader>
            <SheetTitle>
              {component?.name} <code>{version?.label}</code>
            </SheetTitle>
          </SheetHeader>
          {version && data && (
            <>
              <div className="ce-version-meta">
                <Badge variant="outline">
                  {version.parent_id
                    ? `来自 ${data.versions.find((v) => v.id === version.parent_id)?.label}`
                    : "初始版本"}
                </Badge>
                <span>第 {version.round} 轮</span>
                <span>{version.digest.slice(0, 10)}</span>
              </div>
              <div className={`ce-verdict ${decision?.outcome || "unknown"}`}>
                <strong>
                  {decision
                    ? decisionLabels[decision.outcome]
                    : "待评测"}
                </strong>
                <p>
                  {decision?.reason ||
                    "暂无评测记录。"}
                </p>
                {decision?.scope === "bundle" && (
                  <small>判定范围：完整配置，不代表单组件因果贡献。</small>
                )}
              </div>
              <div className="ce-evidence-tabs">
                {(
                  [
                    { id: "diff", name: "组件差异", Icon: Code2 },
                    { id: "trace", name: "执行证据", Icon: Terminal },
                    { id: "answer", name: "回答产物", Icon: FileText },
                  ] as const
                ).map((t) => (
                  <button
                    key={t.id}
                    aria-pressed={tab === t.id}
                    onClick={() => {
                      setTab(t.id);
                      setArtifact(null);
                      setArtifactError("");
                    }}
                  >
                    <t.Icon size={13} />
                    {t.name}
                  </button>
                ))}
              </div>
              <div className="ce-evidence-scroll">
                {tab === "diff" ? (
                  <>
                    {version.files.length ? (
                      version.files.map((f) => (
                        <details key={f.path}>
                          <summary>
                            {f.path}
                            <ChevronDown size={12} />
                          </summary>
                          <pre>{f.diff}</pre>
                        </details>
                      ))
                    ) : (
                      <p>
                        {version.step === 0
                          ? "初始版本"
                          : "无变更"}
                      </p>
                    )}
                    {!version.present && <p>该版本的组件内容为空。</p>}
                    {decision?.evidence && (
                      <details>
                        <summary>
                          查看判定依据
                          <ChevronDown size={12} />
                        </summary>
                        <p>{decision.evidence}</p>
                      </details>
                    )}
                    {version.notes && (
                      <details>
                        <summary>
                          来源修改说明
                          <ChevronDown size={12} />
                        </summary>
                        <p>{version.notes}</p>
                      </details>
                    )}
                  </>
                ) : artifactError ? (
                  <p role="alert">{artifactError}</p>
                ) : !artifact ? (
                  <p>正在读取…</p>
                ) : (
                  <>
                    <p className="ce-evidence-muted">{artifact.caption}</p>
                    {artifact.missing ? (
                      <p>接入记录尚未提供此项证据。</p>
                    ) : (
                      <pre>{artifact.text}</pre>
                    )}
                    {artifact.truncated && <p>长记录截断至500,000字符。</p>}
                  </>
                )}
              </div>
            </>
          )}
        </SheetContent>
      </Sheet>
    </div>
  );
}
