"use client";
import {useEffect, useState, type CSSProperties, type ReactNode} from 'react';
import {Check, ChevronDown, Loader2, ShieldCheck} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Select, SelectTrigger, SelectValue, SelectContent, SelectItem} from '@/components/ui/select';
import {COMPONENT_COLORS} from '@/lib/component-types';
import {componentLabels, platformRead, type Options, type Preview, type Settings} from '@/lib/console-types';
const primary = new Set(['HAI_TOTAL_CREATION_BUDGET','HAI_TRAIN_ROLLOUT_REPEATS','HAI_TEST_ROLLOUT_REPEATS','HAI_MAX_ROLLOUT_CONCURRENCY','HAI_MAX_ANALYSIS_CONCURRENCY','HAI_PROVIDER_MAX_CONCURRENCY']);
export default function ExperimentConfiguration({options, profiles, busy, error, onSubmit, onCancel}: {
  options: Options | null; profiles: string[]; busy: boolean; error: string;
  onSubmit: (profile: string, settings: Settings) => Promise<void>; onCancel: () => void;
}) {
  const [profile, setProfile] = useState('');
  const [benchmarkChoice,setBenchmarkChoice] = useState('');
  const [benchmarkPath,setBenchmarkPath] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [localError, setLocalError] = useState('');
  const selectedProfile = profile || (profiles.includes('crm-local.toml') ? 'crm-local.toml' : profiles[0] || '');
  useEffect(() => {
    if (!selectedProfile) return;
    const abort = new AbortController();
    void platformRead<Preview>('?' + new URLSearchParams({profiles:'1',name:selectedProfile}), {signal:abort.signal})
      .then(value => {setPreview(value); setSettings({models:value.model_selection, components:value.components, parameters:value.parameters, initial_harness:value.initial_harness || '', full_evaluation:value.mode === 'train' && !!value.full_evaluation}); setLocalError('');})
      .catch(e => {if (!abort.signal.aborted) setLocalError((e as Error).message);});
    return () => abort.abort();
  }, [selectedProfile]);
  function toggleComponent(id: string) {
    if (!settings || !options) return;
    const allowed = settings.components.allowed.includes(id) ? settings.components.allowed.filter(x => x !== id) : [...settings.components.allowed,id];
    setSettings({...settings,components:{...settings.components,allowed,denied:options.components.filter(c => !allowed.includes(c.id)).map(c => c.id)}});
  }
  const defaultBenchmark = preview?.benchmark_selection || preview?.benchmark || '';
  const selectedChoice = benchmarkChoice || (options?.benchmarks.some(row => row.id === defaultBenchmark) ? defaultBenchmark : defaultBenchmark ? 'custom' : '');
  const benchmark = selectedChoice === 'custom' ? benchmarkPath || (!benchmarkChoice ? defaultBenchmark : '') : selectedChoice;
  const invalidModels = !settings?.models.execution || !settings?.models.analysis;
  return <section className="console-config-editor" aria-label="Experiment configuration">
    <form className="console-config-form" onSubmit={e => {e.preventDefault(); if (settings && preview?.readiness === 'ready') void onSubmit(selectedProfile,{...settings,benchmark});}}>
      <div className="console-config-scroll">
        {(error || localError) && <div className="console-alert" role="alert">{error || localError}</div>}
        <section className="config-section"><h3>Experiment setup</h3><div className="config-grid">
          <ConfigField label="Benchmark" hint="Choose a benchmark or use your own dataset."><Select value={selectedChoice} onValueChange={setBenchmarkChoice} disabled={busy || !options || !preview}><SelectTrigger aria-label="Benchmark"><SelectValue placeholder="Select a benchmark"/></SelectTrigger><SelectContent>{options?.benchmarks.map(row => <SelectItem key={row.id} value={row.id}>{row.label}</SelectItem>)}<SelectItem value="custom">Custom benchmark</SelectItem></SelectContent></Select></ConfigField>
          {selectedChoice === 'custom' && <ConfigField label="Benchmark file" hint="Path to the benchmark TOML on the server."><Input aria-label="Benchmark file" required disabled={busy} value={benchmark} placeholder="/path/to/benchmark.toml" onChange={event => {setBenchmarkChoice('custom');setBenchmarkPath(event.target.value);}}/></ConfigField>}
          <ConfigField label="Runtime profile" hint="Agent connection and environment."><Select value={selectedProfile} onValueChange={value => {setProfile(value); setPreview(null); setSettings(null);}} disabled={busy}><SelectTrigger aria-label="Runtime profile"><SelectValue placeholder="Select a profile"/></SelectTrigger><SelectContent>{profiles.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent></Select></ConfigField>
        </div>{settings && <ConfigField label="Initial Harness" hint="Server path. Leave empty for an empty starting Harness." className="config-harness"><Input aria-label="Initial Harness" disabled={busy} value={settings.initial_harness} onChange={e => setSettings({...settings,initial_harness:e.target.value})} placeholder="/path/to/harness or exported package"/></ConfigField>}</section>
        {options && settings && preview ? <>
          <section className="config-section"><h3>Model connections</h3><div className="config-grid">{(['execution','analysis'] as const).map(role => <ConfigField key={role} label={role === 'execution' ? 'Execution model' : 'Analysis model'} hint={role === 'execution' ? 'Solves benchmark tasks.' : 'Analyzes traces and proposes improvements.'}><Select value={settings.models[role]} disabled={busy || (role === 'execution' && preview.business_agent)} onValueChange={value => setSettings({...settings,models:{...settings.models,[role]:value}})}><SelectTrigger aria-label={role === 'execution' ? 'Execution model' : 'Analysis model'}><SelectValue placeholder="Select a model"/></SelectTrigger><SelectContent>{role === 'execution' && preview.business_agent ? <SelectItem value="business_agent">Managed by business agent</SelectItem> : options.models.map(m => <SelectItem key={m.id} value={m.id} disabled={!m.configured}>{m.label}{!m.configured ? ' · Key unavailable' : ''}</SelectItem>)}</SelectContent></Select></ConfigField>)}</div><p className="config-note"><ShieldCheck size={13}/>Credentials stay on the server. The benchmark defines its scorer separately.</p></section>
          <section className="config-section"><div className="config-section-heading"><h3>Editable components <b>{settings.components.allowed.length}/16</b></h3><div><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSettings({...settings,components:{...settings.components,allowed:options.components.map(c => c.id),denied:[]}})}>Select all</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSettings({...settings,components:{...settings.components,allowed:[],denied:options.components.map(c => c.id)}})}>Clear</Button></div></div><p className="config-note">Allowed components remain subject to discovery and runtime preflight.</p><div className="config-components">{options.components.map((c,i) => <label key={c.id} style={{'--component-color':COMPONENT_COLORS[i % COMPONENT_COLORS.length]} as CSSProperties} className={settings.components.allowed.includes(c.id) ? 'is-selected' : ''}><input type="checkbox" disabled={busy} checked={settings.components.allowed.includes(c.id)} onChange={() => toggleComponent(c.id)}/><span className="config-component-dot"/><span className="config-component-name">{componentLabels[c.id] || c.id}</span><span className="config-check"><Check size={11}/></span></label>)}</div>{settings.components.allowed.includes('experimental_policies') && <fieldset className="config-experimental"><legend>Allowed experimental fields</legend>{options.experimental_fields.map(field => <label key={field}><input type="checkbox" disabled={busy} checked={settings.components.experimental_fields.includes(field)} onChange={() => setSettings({...settings,components:{...settings.components,experimental_fields:settings.components.experimental_fields.includes(field) ? settings.components.experimental_fields.filter(x => x !== field) : [...settings.components.experimental_fields,field]}})}/>{field}</label>)}</fieldset>}{settings.components.allowed.length === 0 && <p className="config-note">No component edits are allowed. This run can only retain its initial Harness.</p>}</section>
          <section className="config-section"><h3>Evolution settings</h3><div className="config-grid config-numbers">{options.parameters.filter(p => primary.has(p.key)).map(p => <ConfigField key={p.key} label={p.label} hint={`${p.min}–${p.max}`}><Input aria-label={p.label} type="number" disabled={busy} required min={p.min} max={p.max} step={1} value={settings.parameters[p.key] ?? p.default} onChange={e => setSettings({...settings,parameters:{...settings.parameters,[p.key]:Number(e.target.value)}})}/></ConfigField>)}</div><p className="config-note">Creation budget covers TRAIN sessions; it is not a total cost limit.</p><details className="config-advanced"><summary><ChevronDown size={13}/>Advanced settings</summary><div className="config-grid config-numbers">{options.parameters.filter(p => !primary.has(p.key) && (!preview.business_agent || p.key !== 'HAI_CRM_TIMEOUT_S')).map(p => <ConfigField key={p.key} label={p.label} hint={`${p.min}–${p.max}`}><Input aria-label={p.label} type="number" disabled={busy} required min={p.min} max={p.max} step={1} value={settings.parameters[p.key] ?? p.default} onChange={e => setSettings({...settings,parameters:{...settings.parameters,[p.key]:Number(e.target.value)}})}/></ConfigField>)}</div></details></section>
          {preview.mode === 'train' && <label className="config-test"><input type="checkbox" disabled={busy} checked={settings.full_evaluation} onChange={e => setSettings({...settings,full_evaluation:e.target.checked})}/><span><strong>Evaluate on TEST after training</strong><small>Freeze the selected version before evaluating held-out tasks.</small></span></label>}
          {preview.readiness !== 'ready' && <div className="console-alert">This profile is not ready. Complete the business, data and trace integration before starting. Select a ready profile to continue.</div>}
        </> : <div className="config-loading"><Loader2 size={17} className="animate-spin"/>Loading server configuration…</div>}
      </div><footer className="console-config-footer"><Button type="button" variant="outline" disabled={busy} onClick={onCancel}>Cancel</Button><Button type="submit" disabled={busy || !settings || !benchmark.trim() || invalidModels || preview?.readiness !== 'ready'}>{busy && <Loader2 size={14} className="animate-spin"/>}Start run</Button></footer>
    </form>
  </section>;
}

function ConfigField({label,hint,className = "",children}: {label:string;hint?:string;className?:string;children:ReactNode}) {
  return <label className={`config-field ${className}`}><span className="config-field-label"><span>{label}</span>{hint && <small>{hint}</small>}</span>{children}</label>;
}
