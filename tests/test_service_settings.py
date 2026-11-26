"""Task settings freeze, independent model routing, and real evidence import."""
import importlib
import json
from pathlib import Path

import pytest

from harnesslens.service.config import invocation, load_profile
from harnesslens.service.settings import catalog, profile_preview, snapshot_profile
from harnesslens.service.store import Store


@pytest.fixture
def profile(tmp_path, model_tables):
    path = tmp_path / 'ready.toml'
    path.write_text('schema="harnesslens.experiment.v1"\nbenchmark="crm"\n' + model_tables)
    return path


def test_snapshot_freezes_choices_and_runtime_without_touching_source(tmp_path, profile):
    original = profile.read_bytes()
    preview = profile_preview(profile, tmp_path)
    choice = preview['model_selection']
    saved = snapshot_profile(profile, {'models': {'execution': choice['analysis'], 'analysis': choice['execution']},
        'components': {'allowed': ['skills'], 'denied': ['commands']},
        'parameters': {'HAI_TOTAL_CREATION_BUDGET': 80, 'HAI_MAX_ROLLOUT_CONCURRENCY': 3, 'HAI_TEST_ROLLOUT_REPEATS': 1},
        'initial_harness': '', 'full_evaluation': True}, tmp_path / 'snapshot', tmp_path)
    loaded = load_profile(saved)
    assert profile.read_bytes() == original
    assert loaded['components']['allowed'] == ['skills']
    assert loaded['components']['denied'] == ['commands']
    argv, env = invocation(loaded, 'settings-check')
    assert 'harnesslens.service.experiment' in argv
    assert env['HAI_EXECUTION_MODEL'] == 'test/analysis'
    assert env['HAI_EXECUTION_API_KEY'] == 'analysis-test-only'
    assert env['HAI_ANALYSIS_MODEL'] == 'test/execution'
    assert env['HAI_ANALYSIS_API_KEY'] == 'execution-test-only'
    assert env['HAI_CRM_MAX_CONCURRENCY'] == env['HAI_MAX_ROLLOUT_CONCURRENCY'] == '3'
    assert env['HAI_TOTAL_CREATION_BUDGET'] == '80'
    assert 'test-only' not in saved.read_text()
    public = catalog(tmp_path, discover=False)
    assert len(public['components']) == 16 and len(public['proposal_only']) == 5
    assert 'test-only' not in json.dumps(public)


@pytest.mark.parametrize('settings', [
    {'parameters': {'HAI_TOTAL_CREATION_BUDGET': 0}},
    {'parameters': {'HAI_MAX_ROLLOUT_CONCURRENCY': True}},
    {'parameters': {'arbitrary': 1}},
    {'components': {'allowed': ['model']}},
    {'full_evaluation': 'true'},
    {'models': {'execution': 'unregistered:test/execution', 'analysis': 'missing'}},
])
def test_invalid_settings_fail_before_a_job_or_model_launch(tmp_path, profile, settings):
    store = Store(tmp_path / 'state')
    with pytest.raises(ValueError): store.create('bad', profile, settings, tmp_path)
    assert store.list() == []


def test_canonical_role_refs_can_be_cross_swapped():
    from harnesslens.core.model_config import configure_models
    env = {'HAI_EXECUTION_API_KEY': 'exec-private', 'HAI_ANALYSIS_API_KEY': 'analysis-private',
           'HAI_EXECUTION_BASE_URL': 'http://127.0.0.1:10001/v1', 'HAI_ANALYSIS_BASE_URL': 'http://127.0.0.1:10002/v1'}
    models = {'execution': {'model': 'other/analysis', 'api': 'responses', 'base_url_env': 'HAI_ANALYSIS_BASE_URL', 'api_key_env': 'HAI_ANALYSIS_API_KEY'},
              'analysis': {'model': 'other/execution', 'api': 'chat_completions', 'base_url_env': 'HAI_EXECUTION_BASE_URL', 'api_key_env': 'HAI_EXECUTION_API_KEY'}}
    configure_models(models, env)
    assert env['HAI_EXECUTION_API_KEY'] == 'analysis-private'
    assert env['HAI_ANALYSIS_API_KEY'] == 'exec-private'
    assert env['HAI_ANALYSIS_BASE_URL'].endswith(':10001/v1')


def test_import_finished_cli_evidence_is_read_only_and_idempotent(tmp_path, monkeypatch, profile):
    import harnesslens.service.config as config
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    for identity, stage, status in [('finished', 'test_initial', 'succeeded'), ('failed', 'train', 'failed'), ('offline', 'offline_preflight', 'succeeded'), ('active', 'train', 'running')]:
        directory = tmp_path / 'runs/local_experiments' / identity
        directory.mkdir(parents=True)
        (directory / 'configuration.json').write_text(json.dumps({'profile': str(profile)}))
        (directory / 'stage.json').write_text(json.dumps({'stage': stage, 'status': status}))
        if identity == 'finished': (directory / 'result.json').write_text('{}')
    store = Store(tmp_path / 'state')
    # A completed result must contain a receipt, not an empty/incomplete file.
    (tmp_path / 'runs/local_experiments/finished/result.json').write_text('{"selected_version":"v0"}')
    store.sync_local_runs(); store.sync_local_runs()
    assert {r['id'] for r in store.list()} == {'finished', 'failed'}
    assert store.get('finished')['state'] == 'succeeded'
    assert len(store.events('finished')) == 1
    with pytest.raises(ValueError, match='read-only'): store.transition('failed', 'resume')
    assert store.claim() is None


@pytest.mark.parametrize('selected,repeats,stages', [('v0', 1, ['train','test_initial']), ('candidate-01', 2, ['train','test_initial','test_selected'])])
def test_ui_full_evaluation_freezes_parent_and_preserves_test_repeats(tmp_path, monkeypatch, profile, selected, repeats, stages):
    import harnesslens.service.experiment as experiment
    import scripts.run_crm_experiment as launcher
    import harnesslens.harnesses.initial_harness as initial
    import harnesslens.harnesses.opencode_package as package
    monkeypatch.setattr(experiment, 'ROOT', tmp_path)
    (tmp_path / 'configs').mkdir()
    (tmp_path / 'configs/crmarenapro_split.json').write_text('{"train":["query1"],"test":["query13"]}')
    p = snapshot_profile(profile, {'parameters': {'HAI_TEST_ROLLOUT_REPEATS': repeats}}, tmp_path / 'snapshot', tmp_path)
    calls = []
    def execute(argv, env, stage, directory):
        calls.append((stage, argv))
        if stage == 'train':
            target = tmp_path / 'runs/train/ui/submission/final.json'
            target.parent.mkdir(parents=True)
            target.write_text(json.dumps({'selected_version': selected}))
    monkeypatch.setattr(launcher, 'execute', execute)
    monkeypatch.setattr(initial, 'freeze_initial_harness', lambda **kwargs: {'workspace': {'files': []}, 'manifest': {}})
    monkeypatch.setattr(package, 'export_package', lambda **kwargs: {'path': '/frozen/v0.json'})
    experiment.run(p, 'ui')
    assert [c[0] for c in calls] == stages
    for stage, argv in calls[1:]:
        assert argv[argv.index('--repeats') + 1] == str(repeats)
    assert '--initial-harness' in calls[1][1]
    assert json.loads((tmp_path / 'runs/local_experiments/ui/result.json').read_text())['test_repeats'] == repeats


def test_full_evaluation_rejects_overlong_test_id_before_training(tmp_path, profile):
    loaded = {**load_profile(profile), 'full_evaluation': True}
    with pytest.raises(ValueError, match='Invalid run ID'): invocation(loaded, 'x' * 92)


def test_history_attaches_only_actual_bundle_reviews_and_non_preflight_scores(tmp_path, monkeypatch):
    module = importlib.import_module('harnesslens.service.history')
    monkeypatch.setattr(module, 'ROOT', tmp_path)
    root = tmp_path / 'runs/train/reviews'
    for rel, data in {
        'baseline/bootstrap_event.json': {'metrics': {'pass_at_1': .75}},
        'rollout/iteration-01-candidate-01-channel-preflight.json': {'harness_version': 'candidate-01', 'metrics': {'pass_at_1': 0}},
        'submission/final.json': {'selected_version': 'v0', 'iteration_history': [{'iteration': 1, 'candidate_version': 'candidate-01', 'selected_version': 'v0', 'review_decision': 'channel_preflight_failed', 'review_rationale': 'Command not invoked'}]},
        'rollout_evidence/run/versions_percell/crm/candidate-01/harness/opencode/workspace.json': {'files': [{'scope': 'project', 'path': '.opencode/commands/test.md', 'content': 'candidate'}]},
    }.items():
        p = root / rel; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(json.dumps(data))
    result = module.history('reviews')
    assert result['bundles'][0]['metrics']['score'] == .75
    assert result['bundles'][1]['metrics'] == {}
    assert result['decisions'] == [{'version_id': 'candidate-01', 'step': 1, 'scope': 'bundle', 'outcome': 'not_retained', 'reason': 'Command not invoked', 'evidence': 'channel_preflight_failed'}]


@pytest.mark.parametrize('state,checkpoint,launcher,expected', [
    ('draft', {}, {}, 'Not started'),
    ('queued', {}, {}, 'Queued'),
    ('running', {}, {'stage':'train'}, 'Baseline evaluation'),
    ('running', {'stage':'baseline_ready'}, {'stage':'train'}, 'Discovery'),
    ('failed', {'stage':'discovery_complete'}, {'stage':'train'}, 'Experience'),
    ('running', {'stage':'experience_complete'}, {'stage':'train'}, 'Analysis'),
    ('running', {'stage':'iteration-01_reviewed'}, {'stage':'train'}, 'Evolution'),
    ('running', {'stage':'finalized'}, {'stage':'test_initial'}, 'TEST evaluation'),
    ('succeeded', {'stage':'finalized'}, {'stage':'test_initial'}, 'TEST complete'),
])
def test_live_phase_follows_persisted_records_without_a_synthetic_percentage(state, checkpoint, launcher, expected):
    from harnesslens.service.records import execution_phase
    actual = execution_phase({'state':state},checkpoint,launcher,False)
    assert actual['label'] == expected
    assert actual['initial_ready'] is False
    assert 'percent' not in actual


def test_live_history_has_no_claimed_initial_snapshot_before_freezing(tmp_path, monkeypatch):
    module = importlib.import_module('harnesslens.service.history')
    monkeypatch.setattr(module,'ROOT',tmp_path)
    assert module.history('waiting')['context']['initial_ready'] is False


def test_live_preflight_rejection_preserves_actual_nonempty_parent(tmp_path, monkeypatch):
    module=importlib.import_module('harnesslens.service.history')
    monkeypatch.setattr(module,'ROOT',tmp_path)
    root=tmp_path/'runs/train/live'
    payloads={
        'rollout_evidence/run/versions_percell/crm/champion/harness/opencode/workspace.json': {'files':[{'scope':'project','path':'AGENTS.md','content':'parent'}]},
        'rollout_evidence/run/versions_percell/crm/champion/lineage.json': {'parent':'v0'},
        'rollout_evidence/run/versions_percell/crm/candidate-02/harness/opencode/workspace.json': {'files':[{'scope':'project','path':'AGENTS.md','content':'candidate'}]},
        'rollout_evidence/run/versions_percell/crm/candidate-02/lineage.json': {'parent':'champion'},
        'channel_preflight/iteration-02-candidate-02.json': {'harness_version':'candidate-02','passed':False},
        'main_agent/iteration-02.json': {'harness_version':'candidate-02','candidate':{'parent_version':'champion'}},
    }
    for relative,value in payloads.items():
        p=root/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value))
    result=module.history('live')
    assert result['steps'][-1]['active_bundle_id']=='champion'
    assert result['decisions'][-1]['outcome']=='not_retained'
    assert result['decisions'][-1]['scope']=='bundle'


def test_benchmark_can_be_selected_independently_of_runtime_profile(tmp_path, profile):
    original = profile.read_bytes()
    available = {row['id'] for row in catalog(tmp_path, discover=False)['benchmarks']}
    assert {'crm', 'retail', 'banking', 'bird', 'terminal-bench'} <= available
    saved = snapshot_profile(profile, {'benchmark': 'retail'}, tmp_path/'selected', tmp_path)
    loaded = load_profile(saved)
    assert loaded['benchmark'] == 'retail'
    assert profile.read_bytes() == original
    argv, _ = invocation(loaded, 'benchmark-check')
    assert argv[argv.index('--cell')+1] == 'retail'


def test_custom_benchmark_descriptor_is_validated_and_frozen(tmp_path, profile):
    tasks = tmp_path/'tasks.jsonl'
    tasks.write_text('\n'.join(json.dumps({'id':str(i),'question':'Question','answer':'Answer'}) for i in range(2)))
    descriptor = tmp_path/'benchmark.toml'
    descriptor.write_text('schema="harnesslens.business-benchmark.v1"\nid="customqa"\ntasks="tasks.jsonl"\ntrain=["0"]\ntest=["1"]\n')
    saved = snapshot_profile(profile, {'benchmark': str(descriptor)}, tmp_path/'custom', tmp_path)
    loaded = load_profile(saved)
    assert loaded['benchmark'] == str(descriptor)
    assert '--cell' in invocation(loaded,'custom-check')[0]
    descriptor.write_text(descriptor.read_text().replace('train=["0"]','train=["missing"]'))
    with pytest.raises(ValueError,match='unavailable'):
        snapshot_profile(profile, {'benchmark': str(descriptor)}, tmp_path/'invalid-custom', tmp_path)


@pytest.mark.parametrize('benchmark',[None, '', 'unknown-benchmark', '/missing/benchmark.toml'])
def test_invalid_benchmark_rejected_before_run_is_created(tmp_path, profile, benchmark):
    store = Store(tmp_path/'state')
    with pytest.raises(ValueError): store.create('invalid-benchmark',profile,{'benchmark':benchmark},tmp_path)
    assert not store.list()


def test_declaration_choices_survive_snapshot_preview_and_invocation(tmp_path, profile):
    path = snapshot_profile(profile, {'components': {'allowed':['skills'], 'proposal_only':['diagnostic','tool_return']}}, tmp_path/'declaration-snapshot', tmp_path)
    loaded = load_profile(path)
    assert loaded['components']['proposal_only'] == ['diagnostic','tool_return']
    assert profile_preview(path,tmp_path)['components']['proposal_only'] == ['diagnostic','tool_return']
    _, env = invocation(loaded,'declaration-roundtrip')
    assert json.loads(env['HAI_COMPONENT_POLICY'])['proposal_only'] == ['diagnostic','tool_return']
    path2 = snapshot_profile(profile, {'components': {'proposal_only':[]}}, tmp_path/'no-declarations', tmp_path)
    assert load_profile(path2)['components']['proposal_only'] == []
