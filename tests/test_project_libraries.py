"""Local discovery, reusable immutable Harness outputs, and benchmark metadata."""
import json
from pathlib import Path
import uuid
import pytest
from harnesslens.service.library import benchmark_entries,harness_entries,selected_harness
from harnesslens.harnesses.library import sync_run_harnesses
from harnesslens.harnesses.initial_harness import load_initial_harness
from harnesslens.benchmarks.selection import dataset_options

@pytest.fixture
def standard_benchmark(tmp_path,monkeypatch):
    monkeypatch.setenv('HAI_BENCHMARK_CONFIG','')
    name='business-qa-'+uuid.uuid4().hex[:8]
    directory=tmp_path/'benchmarks'/name
    (directory/'data').mkdir(parents=True)
    rows=[{'id':str(i),'question':'Question','answer':'Host-only reference','domain':'finance'} for i in range(8)]
    (directory/'data/tasks.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows))
    manifest=directory/'benchmark.toml'
    manifest.write_text(f'schema="harnesslens.business-benchmark.v1"\nid="{name}"\nname="Business QA"\ntasks="data/tasks.jsonl"\ntrain=["0","1","2","3","4","5"]\ntest=["6","7"]\npublic_fields=["question"]\n')
    return manifest


def test_fixed_benchmark_discovery_and_optional_domain(standard_benchmark,tmp_path,monkeypatch):
    import harnesslens.service.config as config
    from harnesslens.service.settings import selected_benchmark
    monkeypatch.setattr(config,'ROOT',tmp_path)
    entries=benchmark_entries(tmp_path)
    assert len(entries)==1 and entries[0]['label']=='Business QA'
    assert selected_benchmark(entries[0]['id'])==str(standard_benchmark)
    options=dataset_options(str(standard_benchmark))
    assert (options['train_available'],options['test_available'])==(6,2)
    assert options['grouping']=='benchmark' and len(options['domains'])==1
    standard_benchmark.write_text(standard_benchmark.read_text().replace('public_fields=["question"]','public_fields=["question","domain"]\ndomain_field="domain"'))
    options=dataset_options(str(standard_benchmark))
    assert options['grouping']=='domain' and len(options['domains'])==2


def test_standard_manifest_and_data_names_are_enforced(standard_benchmark,tmp_path):
    standard_benchmark.write_text(standard_benchmark.read_text().replace('data/tasks.jsonl','outside.jsonl'))
    with pytest.raises(ValueError,match='data/tasks.jsonl'):benchmark_entries(tmp_path)


def test_manual_harness_directory_is_discovered_and_frozen(tmp_path):
    directory=tmp_path/'harnesses/business-agent/project'
    directory.mkdir(parents=True)
    (directory/'AGENTS.md').write_text('Business rules')
    entries=harness_entries(tmp_path)
    assert len(entries)==1 and entries[0]['id']=='harness:business-agent'
    source=selected_harness(entries[0]['id'],tmp_path)
    index=sync_run_harnesses(tmp_path,'experiment-a',source)
    saved=json.loads(index.read_text())
    package=index.parent/saved['versions']['v0']['path']
    assert load_initial_harness(source)['sha256']==load_initial_harness(package)['sha256']
    (directory/'AGENTS.md').write_text('Changed outside the experiment')
    assert load_initial_harness(package)['workspace']['files'][0]['content']=='Business rules'


def test_new_versions_are_reusable_without_overwriting_the_initial_harness(tmp_path):
    index=sync_run_harnesses(tmp_path,'experiment-a')
    source=tmp_path/'runs/train/experiment-a/rollout_evidence/experiment-a/versions_percell/crm/candidate-01/harness/opencode'
    source.mkdir(parents=True)
    workspace={'schema':1,'files':[{'scope':'project','path':'AGENTS.md','content':'Improved rule','executable':False}]}
    (source/'workspace.json').write_text(json.dumps(workspace));(source/'manifest.json').write_text('{}')
    final=tmp_path/'runs/train/experiment-a/submission/final.json';final.parent.mkdir();final.write_text('{"selected_version":"v0"}')
    sync_run_harnesses(tmp_path,'experiment-a')
    first=index.read_bytes();sync_run_harnesses(tmp_path,'experiment-a');assert index.read_bytes()==first
    choices=harness_entries(tmp_path)
    assert len(choices)==2
    selected=next(row for row in choices if row['id'].endswith('/v0'));assert 'Selected' in selected['label']
    candidate=selected_harness('harness:experiment-a/candidate-01',tmp_path)
    assert load_initial_harness(candidate)['workspace']==workspace
    next_index=sync_run_harnesses(tmp_path,'experiment-b',candidate)
    raw=json.loads(next_index.read_text())
    assert load_initial_harness(next_index.parent/raw['versions']['v0']['path'])['workspace']==workspace


def test_library_rejects_traversal_and_does_not_overwrite_manual_inputs(tmp_path):
    with pytest.raises(ValueError):sync_run_harnesses(tmp_path,'../outside')
    directory=tmp_path/'harnesses/manual';directory.mkdir(parents=True);(directory/'AGENTS.md').write_text('Keep me')
    with pytest.raises(ValueError,match='already exists'):sync_run_harnesses(tmp_path,'manual')
    assert (directory/'AGENTS.md').read_text()=='Keep me'
    assert not (directory/'library.json').exists()


def test_task_snapshot_resolves_harness_library_choice(tmp_path,monkeypatch,model_tables):
    import harnesslens.service.config as config
    from harnesslens.service.settings import snapshot_profile,profile_preview
    monkeypatch.setattr(config,'ROOT',tmp_path)
    source=tmp_path/'harnesses/manual/project';source.mkdir(parents=True);(source/'AGENTS.md').write_text('Initial instructions')
    profile=tmp_path/'runtime.toml';profile.write_text('schema="harnesslens.experiment.v1"\nbenchmark="crm"\n'+model_tables)
    saved=snapshot_profile(profile,{'initial_harness':'harness:manual'},tmp_path/'job',tmp_path)
    loaded=config.load_profile(saved)
    assert loaded['initial_harness']==str(source.parent)
    assert profile_preview(profile,tmp_path)['initial_harness_selection']==''
    assert load_initial_harness(loaded['initial_harness'])['workspace']['files'][0]['content']=='Initial instructions'


def test_backfill_uses_the_recorded_initial_snapshot(tmp_path):
    run=tmp_path/'runs/train/existing';native=run/'rollout_evidence/existing/versions_percell/crm/v0/harness/opencode';native.mkdir(parents=True)
    workspace={'schema':1,'files':[{'scope':'project','path':'AGENTS.md','content':'Actual recorded baseline','executable':False}]}
    (native/'workspace.json').write_text(json.dumps(workspace));(native/'manifest.json').write_text('{}')
    (run/'initial_harness.json').write_text(json.dumps({'snapshot_path':str(native.parents[1])}))
    index=sync_run_harnesses(tmp_path,'existing');raw=json.loads(index.read_text())
    assert load_initial_harness(index.parent/raw['versions']['v0']['path'])['workspace']==workspace
