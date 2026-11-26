"use client";
import {useEffect, useState} from 'react';
import {Check, ChevronDown, Loader2, ShieldCheck} from 'lucide-react';
import {Button} from '@/components/ui/button';
import {Input} from '@/components/ui/input';
import {Select, SelectTrigger, SelectValue, SelectContent, SelectItem} from '@/components/ui/select';
import {componentLabels, platformRead, type Options, type Preview, type Settings} from '@/lib/console-types';
const primary = new Set(['HAI_TOTAL_CREATION_BUDGET','HAI_TRAIN_ROLLOUT_REPEATS','HAI_TEST_ROLLOUT_REPEATS','HAI_MAX_ROLLOUT_CONCURRENCY','HAI_MAX_ANALYSIS_CONCURRENCY','HAI_PROVIDER_MAX_CONCURRENCY']);
export default function ExperimentConfiguration({options, profiles, busy, error, onSubmit}: {
  options: Options | null; profiles: string[]; busy: boolean; error: string;
  onSubmit: (profile: string, id: string, settings: Settings, start: boolean) => Promise<void>;
}) {
  const [profile, setProfile] = useState('');
  const [preview, setPreview] = useState<Preview | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [id, setId] = useState('');
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
  const invalidModels = !settings?.models.execution || !settings?.models.analysis;
  return <section className="console-config-editor" aria-label="Experiment configuration">
    <header className="config-editor-heading"><h2>Experiment configuration</h2><p>Set up the benchmark, models, components and evolution in one place.</p></header>
    <form className="console-config-form" onSubmit={e => {e.preventDefault(); if (settings && preview?.readiness === 'ready') void onSubmit(selectedProfile,id,settings,true);}}>
      <div className="console-config-scroll">
        {(error || localError) && <div className="console-alert" role="alert">{error || localError}</div>}
        <section className="config-section"><h3><span>01</span>Experiment setup</h3><div className="config-grid">
          <label className="config-field">Profile<Select value={selectedProfile} onValueChange={value => {setProfile(value); setPreview(null); setSettings(null);}} disabled={busy}><SelectTrigger aria-label="Profile"><SelectValue placeholder="Select a profile"/></SelectTrigger><SelectContent>{profiles.map(p => <SelectItem key={p} value={p}>{p}</SelectItem>)}</SelectContent></Select></label>
          <label className="config-field">Run ID <small>Optional</small><Input aria-label="Run ID" value={id} disabled={busy} placeholder="Generated automatically" maxLength={91} pattern="[A-Za-z0-9][A-Za-z0-9_-]{0,90}" onChange={e => setId(e.target.value)}/></label>
        </div>{preview && <div className="config-profile-context"><span>Benchmark <strong>{preview.benchmark}</strong></span><span>{preview.business_agent ? 'Business HTTP / Python' : 'Native OpenCode'}</span></div>}{settings && <label className="config-field config-harness">Initial Harness<Input aria-label="Initial Harness" disabled={busy} value={settings.initial_harness} onChange={e => setSettings({...settings,initial_harness:e.target.value})} placeholder="/path/to/harness or exported package"/><small>Server path. Leave empty for an empty initial Harness.</small></label>}</section>
        {options && settings && preview ? <>
          <section className="config-section"><h3><span>02</span>Model connections</h3><div className="config-grid">{(['execution','analysis'] as const).map(role => <label className="config-field" key={role}>{role === 'execution' ? 'Execution model' : 'Analysis model'}<Select value={settings.models[role]} disabled={busy || (role === 'execution' && preview.business_agent)} onValueChange={value => setSettings({...settings,models:{...settings.models,[role]:value}})}><SelectTrigger aria-label={role === 'execution' ? 'Execution model' : 'Analysis model'}><SelectValue placeholder="Select a model"/></SelectTrigger><SelectContent>{role === 'execution' && preview.business_agent ? <SelectItem value="business_agent">Managed by business agent</SelectItem> : options.models.map(m => <SelectItem key={m.id} value={m.id} disabled={!m.configured}>{m.label}{!m.configured ? ' · Key unavailable' : ''}</SelectItem>)}</SelectContent></Select><small>{role === 'execution' ? 'Solves benchmark tasks.' : 'Discovers, analyzes and proposes improvements.'}</small></label>)}</div><p className="config-note"><ShieldCheck size={13}/>Credentials stay on the server. The benchmark defines its scorer separately.</p></section>
          <section className="config-section"><div className="config-section-heading"><h3><span>03</span>Editable components <b>{settings.components.allowed.length}/16</b></h3><div><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSettings({...settings,components:{...settings.components,allowed:options.components.map(c => c.id),denied:[]}})}>Select all</Button><Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => setSettings({...settings,components:{...settings.components,allowed:[],denied:options.components.map(c => c.id)}})}>Clear</Button></div></div><p className="config-note">Allowed components remain subject to discovery and runtime preflight.</p><div className="config-components">{options.components.map((c,i) => <label key={c.id} className={settings.components.allowed.includes(c.id) ? 'is-selected' : ''}><input type="checkbox" disabled={busy} checked={settings.components.allowed.includes(c.id)} onChange={() => toggleComponent(c.id)}/><span className="config-check"><Check size={11}/></span><span className="config-component-index">{String(i+1).padStart(2,'0')}</span>{componentLabels[c.id] || c.id}</label>)}</div><details className="config-locked"><summary>5 proposal-only categories remain locked</summary><p>{options.proposal_only.map(c => componentLabels[c] || c).join(' · ')}</p></details>{settings.components.allowed.includes('experimental_policies') && <fieldset className="config-experimental"><legend>Allowed experimental fields</legend>{options.experimental_fields.map(field => <label key={field}><input type="checkbox" disabled={busy} checked={settings.components.experimental_fields.includes(field)} onChange={() => setSettings({...settings,components:{...settings.components,experimental_fields:settings.components.experimental_fields.includes(field) ? settings.components.experimental_fields.filter(x => x !== field) : [...settings.components.experimental_fields,field]}})}/>{field}</label>)}</fieldset>}{settings.components.allowed.length === 0 && <p className="config-note">No component edits are allowed. This run can only retain its initial Harness.</p>}</section>
          <section className="config-section"><h3><span>04</span>Evolution settings</h3><div className="config-grid config-numbers">{options.parameters.filter(p => primary.has(p.key)).map(p => <label className="config-field" key={p.key}>{p.label}<Input aria-label={p.label} type="number" disabled={busy} required min={p.min} max={p.max} step={1} value={settings.parameters[p.key] ?? p.default} onChange={e => setSettings({...settings,parameters:{...settings.parameters,[p.key]:Number(e.target.value)}})}/></label>)}</div><p className="config-note">Creation budget covers TRAIN sessions; it is not a total cost limit.</p><details className="config-advanced"><summary><ChevronDown size={13}/>Advanced settings</summary><div className="config-grid config-numbers">{options.parameters.filter(p => !primary.has(p.key) && (!preview.business_agent || p.key !== 'HAI_CRM_TIMEOUT_S')).map(p => <label className="config-field" key={p.key}>{p.label}<Input aria-label={p.label} type="number" disabled={busy} required min={p.min} max={p.max} step={1} value={settings.parameters[p.key] ?? p.default} onChange={e => setSettings({...settings,parameters:{...settings.parameters,[p.key]:Number(e.target.value)}})}/></label>)}</div></details></section>
          {preview.mode === 'train' && <label className="config-test"><input type="checkbox" disabled={busy} checked={settings.full_evaluation} onChange={e => setSettings({...settings,full_evaluation:e.target.checked})}/><span><strong>Evaluate on TEST after training</strong><small>Freeze the selected version before evaluating held-out tasks.</small></span></label>}
          {preview.readiness !== 'ready' && <div className="console-alert">This profile is not ready. Complete the business, data and trace integration before starting. You can save a draft.</div>}
        </> : <div className="config-loading"><Loader2 size={17} className="animate-spin"/>Loading server configuration…</div>}
      </div><footer className="console-config-footer"><Button type="button" variant="outline" disabled={busy || !settings || invalidModels} onClick={e => {if (e.currentTarget.form?.reportValidity() && settings) void onSubmit(selectedProfile,id,settings,false);}}>Save draft</Button><Button type="submit" disabled={busy || !settings || invalidModels || preview?.readiness !== 'ready'}>{busy && <Loader2 size={14} className="animate-spin"/>}Start run</Button></footer>
    </form>
  </section>;
}
