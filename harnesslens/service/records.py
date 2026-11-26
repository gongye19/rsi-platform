"""Read existing experiment evidence without rerunning or relabeling trials."""
import json
from pathlib import Path
from .config import ROOT, load_profile
from .history import read


def artifacts(identity, state_dir):
    roots = [ROOT / 'runs/train' / identity, Path(state_dir) / 'jobs' / identity,
             ROOT / 'runs/test_baselines' / identity, ROOT / 'runs/test_candidates' / identity,
             ROOT / 'runs/local_experiments' / identity]
    result = read(roots[4] / 'result.json', {})
    test_id = result.get('test_run_id', identity + '-test')
    from .config import run_id
    run_id(test_id)
    roots += [ROOT / 'runs/test_baselines' / test_id, ROOT / 'runs/test_candidates' / test_id]
    continuation = read(roots[0] / 'continuation.json', {})
    if continuation.get('source_run'):
        source = Path(continuation['source_run']).resolve()
        if source.parent == (ROOT / 'runs/train').resolve():
            roots.append(source)
    return roots


def trial_metrics(value):
    if not isinstance(value, dict): return {}
    if 'response' in value: return value['response'].get('metrics', {})
    return value.get('metrics') or value.get('agent_workspace_entry', {}).get('metrics', {})


def run_record(job):
    identity = job['id']; root = ROOT / 'runs/train' / identity
    local = ROOT / 'runs/local_experiments' / identity
    checkpoint = read(root / 'controller_state.json', {})
    budget = read(root / 'creation_budget.json', {})
    if budget:
        from harnesslens.core.budget import CreationBudget
        budget = CreationBudget._status(budget)
    final = read(root / 'submission/final.json', {})
    baseline = trial_metrics(read(root / 'baseline/bootstrap_event.json', {}))
    reuse = read(root / 'baseline/reuse.json', {})
    if not baseline and reuse.get('baseline_event'):
        path = Path(reuse['baseline_event']).resolve()
        if path.is_relative_to((ROOT / 'runs/train').resolve()): baseline = trial_metrics(read(path, {}))
    # Collect the latest completed rollouts; preflight is explicitly identified.
    candidates = []
    for path in sorted((root / 'rollout').glob('*.json')):
        row = read(path, {})
        candidates.append({'label': path.stem, 'version': row.get('harness_version'),
                           'preflight': 'preflight' in path.stem, 'metrics': row.get('metrics', {})})
    test_id = read(local / 'result.json', {}).get('test_run_id', identity + '-test')
    tests = {}
    from .config import run_id
    run_id(test_id)
    for kind in ['test_baselines', 'test_candidates']:
        folder = ROOT / 'runs' / kind / test_id / 'opencode'
        for path in folder.glob('*result.json'):
            value = read(path, {})
            tests['initial' if kind == 'test_baselines' else 'selected'] = {'metrics': trial_metrics(value), 'repeats': value.get('repeats')}
    if final.get('selected_version') == 'v0' and tests.get('initial'):
        tests['selected'] = {**tests['initial'], 'reused_initial': True}
    models = read(root / 'model_connections.json', {}) or read(local / 'configuration.json', {}).get('models', {})
    configuration = {}
    receipt = read(local / 'result.json', {})
    try:
        profile = load_profile(job['profile'])
        configuration = {'benchmark': profile['benchmark'], 'dataset': profile.get('dataset'), 'dataset_selection': read(root/'dataset_selection.json') or read(ROOT/'runs/test_baselines'/identity/'dataset_selection.json') or read(ROOT/'runs/test_candidates'/identity/'dataset_selection.json') or profile.get('dataset_selection'), 'models': profile.get('models'), 'components': profile['components'],
                         'parameters': profile.get('environment', {}), 'initial_harness': profile['initial_harness'],
                         'full_evaluation': bool(receipt) or profile.get('full_evaluation', False)}
        if models: configuration['models'] = models
    except (OSError, ValueError): pass
    return {**job, 'checkpoint': checkpoint, 'budget': budget, 'baseline_metrics': baseline,
            'candidates': candidates, 'tests': tests, 'selected_version': final.get('selected_version'),
            'iteration_history': final.get('iteration_history', []), 'models': models,
            'configuration': configuration, 'stage': read(local / 'stage.json', {}).get('stage') or checkpoint.get('stage'),
            'phase': execution_phase(job, checkpoint, read(local / 'stage.json', {}), (root / 'initial_harness.json').is_file())}


def execution_phase(job, checkpoint, launcher, initial_ready):
    """Expose persisted checkpoints without inventing a completion percentage."""
    state = job['state']
    checkpoint_name = checkpoint.get('stage', '')
    stage = launcher.get('stage', '')
    if state in {'draft', 'queued'}:
        identity, label = state, 'Not started' if state == 'draft' else 'Queued'
    elif stage in {'test_initial', 'test_selected'}:
        identity, label = 'test', 'TEST complete' if state == 'succeeded' else 'TEST evaluation'
    elif checkpoint_name == 'finalized':
        identity, label = 'finalized', 'Completed' if state == 'succeeded' else 'Finalizing'
    elif checkpoint_name.startswith('iteration-'):
        identity, label = 'evolution', 'Evolution'
    else:
        identity, label = {'baseline_ready': ('discovery','Discovery'), 'discovery_complete': ('experience','Experience'),
            'experience_complete': ('analysis','Analysis'), 'analyzer_complete': ('evolution','Evolution')}.get(checkpoint_name, ('baseline','Baseline evaluation'))
    return {'id': identity, 'label': label, 'checkpoint': checkpoint_name, 'initial_ready': initial_ready}
