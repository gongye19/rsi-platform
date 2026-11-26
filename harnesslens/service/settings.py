"""Server-owned configuration choices and immutable per-task profile snapshots."""
import hashlib
import json
from pathlib import Path
import threading
import time
import tomllib

from .config import load_profile, profile_environment
from harnesslens.core.model_config import clean_base_url
from harnesslens.harnesses.component_policy import EXPERIMENTAL_FIELDS
from harnesslens.harnesses.opencode_components import COMPONENTS, PROPOSAL_ONLY

# Bounds mirror the corresponding runtime settings. No invented optimizer knobs.
PARAMETERS = {
    'HAI_TOTAL_CREATION_BUDGET': ('Creation budget', 200, 1, 10000),
    'HAI_TRAIN_ROLLOUT_REPEATS': ('TRAIN repeats per task', 2, 1, 2),
    'HAI_TEST_ROLLOUT_REPEATS': ('TEST repeats per task', 2, 1, 2),
    'HAI_MAX_ROLLOUT_CONCURRENCY': ('Task concurrency', 4, 1, 30),
    'HAI_MAX_ANALYSIS_CONCURRENCY': ('Analysis concurrency', 2, 1, 20),
    'HAI_PROVIDER_MAX_CONCURRENCY': ('Model request concurrency', 4, 1, 64),
    'HAI_CRM_TIMEOUT_S': ('Native execution timeout (s)', 900, 30, 7200),
    'HAI_INTELLIGENT_TIMEOUT_S': ('Analysis timeout (s)', 1200, 30, 7200),
    'HAI_PROVIDER_HTTP_TIMEOUT_S': ('Model request timeout (s)', 180, 1, 7200),
    'HAI_PROVIDER_REQUEST_BUDGET_S': ('Request retry deadline (s)', 420, 1, 7200),
    'HAI_PROVIDER_RETRY_ATTEMPTS': ('Maximum request attempts', 4, 1, 6),
    'HAI_INTELLIGENT_CONTEXT_LIMIT': ('Analysis context limit (tokens)', 200000, 4096, 1050000),
}
_cache = {}
_lock = threading.Lock()


def connections(profiles):
    result = {}
    for path in sorted(Path(profiles).glob('*.toml')):
        try:
            profile = load_profile(path)
            env = profile_environment(profile)
        except (OSError, ValueError):
            continue
        for row in profile.get('models', {}).values():
            if row.get('managed_by'):
                continue
            base = row.get('base_url') or env.get(row.get('base_url_env'), '')
            if not base:
                continue
            base = clean_base_url(base)
            public = {key: row[key] for key in ('api', 'api_key_env', 'base_url', 'base_url_env') if key in row}
            identity = hashlib.sha256(json.dumps([base, row['api'], row['api_key_env']]).encode()).hexdigest()[:16]
            entry = result.setdefault(identity, {'id': identity, 'config': public, 'base': base,
                'key': env.get(row['api_key_env'], ''), 'models': set(), 'provider': row['model'].split('/', 1)[0]})
            entry['models'].add(row['model'])
    return result


def benchmark_choices():
    from .library import benchmark_entries
    return [{'id': row['id'], 'label': row['label']} for row in benchmark_entries()]


def selected_benchmark(value):
    from harnesslens.benchmarks.cell_config import _ALIASES
    if not isinstance(value,str) or not value.strip():
        raise ValueError('Select a benchmark')
    value=value.strip()
    from .library import benchmark_entries
    match=next((row for row in benchmark_entries() if row['id']==value),None)
    if match: value=match['source']
    if value.lower() in _ALIASES:
        return value.lower()
    path=Path(value).expanduser().resolve()
    if path.suffix != '.toml' or not path.is_file():
        raise ValueError('Custom benchmark must be an existing TOML descriptor')
    from harnesslens.benchmarks.jsonl_adapter import JsonlAdapter
    from .config import ROOT
    adapter=JsonlAdapter(ROOT,path)
    adapter._tasks()  # Validate tasks and split without running the scorer.
    return str(path)


def catalog(profiles, *, discover=True):
    choices = []
    for item in connections(profiles).values():
        # Read-only provider discovery. Coding endpoints without /models retain
        # their explicitly configured model; there is no model-generation call.
        models = set(item['models'])
        if discover and item['key']:
            cache_key = (item['id'], hashlib.sha256(item['key'].encode()).hexdigest())
            with _lock:
                cached = _cache.get(cache_key)
            if not cached or time.monotonic() - cached[0] > 600:
                found = []
                try:
                    import httpx
                    response = httpx.get(item['base'] + '/models', headers={'Authorization': 'Bearer ' + item['key']}, timeout=3)
                    if response.status_code == 200:
                        data = response.json()
                        for row in (data.get('data', data.get('models', [])) if isinstance(data, dict) else []):
                            if not isinstance(row, dict): continue
                            model = row.get('id') or row.get('slug')
                            if isinstance(model, str) and model and len(model) < 160:
                                found.append(item['provider'] + '/' + model)
                except (ValueError, OSError, httpx.HTTPError):
                    pass
                cached = (time.monotonic(), found)
                with _lock:
                    _cache[cache_key] = cached
            models.update(cached[1])
        for model in sorted(models):
            choices.append({'id': item['id'] + ':' + model, 'connection_id': item['id'], 'model': model,
                            'api': item['config']['api'], 'configured': bool(item['key']),
                            'label': model + ' · ' + ('Responses' if item['config']['api'] == 'responses' else 'Chat Completions')})
    from .library import harness_entries
    return {'models': choices, 'benchmarks': benchmark_choices(), 'harnesses': harness_entries(), 'components': [{'id': key, 'name': value} for key, value in COMPONENTS],
            'proposal_only': sorted(PROPOSAL_ONLY), 'experimental_fields': sorted(EXPERIMENTAL_FIELDS),
            'parameters': [{'key': k, 'label': v[0], 'default': v[1], 'min': v[2], 'max': v[3]} for k, v in PARAMETERS.items()]}


def profile_preview(path, profiles):
    profile = load_profile(path)
    available = connections(profiles)
    selected = {}
    env = profile_environment(profile)
    for role, row in profile.get('models', {}).items():
        if row.get('managed_by'):
            selected[role] = 'business_agent'
            continue
        base = clean_base_url(row.get('base_url') or env.get(row.get('base_url_env'), ''))
        match = next((c for c in available.values() if c['base'] == base and c['config']['api'] == row['api'] and c['config']['api_key_env'] == row['api_key_env']), None)
        selected[role] = match['id'] + ':' + row['model'] if match else ''
    from harnesslens.benchmarks.cell_config import _ALIASES
    normalized = _ALIASES.get(profile['benchmark'].lower())
    from .library import benchmark_entries, harness_entries
    benchmark_selection = next((row['id'] for row in benchmark_entries() if row['source']==profile['benchmark'] or normalized and _ALIASES.get(row['source'])==normalized),profile['benchmark'])
    harness_selection = next((row['id'] for row in harness_entries() if row['path']==profile['initial_harness']), '')
    return {'name': Path(path).name, 'benchmark': profile['benchmark'], 'benchmark_selection': benchmark_selection, 'mode': profile['mode'],
            'readiness': profile.get('readiness', 'ready'), 'models': profile.get('models', {}),
            'dataset': profile.get('dataset',{'domain':'all','train_count':0,'test_count':0}),
            'dataset_selection': profile.get('dataset_selection'),
            'initial_harness_selection': harness_selection, 'model_selection': selected, 'components': profile['components'], 'initial_harness': profile['initial_harness'],
            'business_agent': bool(profile['agent_config']), 'full_evaluation': profile.get('full_evaluation', True),
            'parameters': {k: int(profile.get('environment', {}).get(k, v[1])) for k, v in PARAMETERS.items()}}


def dump_toml(data):
    lines = []
    def value(v):
        if isinstance(v, str): return json.dumps(v, ensure_ascii=False)
        if isinstance(v, bool): return 'true' if v else 'false'
        if type(v) in {int, float}: return str(v)
        if isinstance(v, list): return '[' + ', '.join(value(x) for x in v) + ']'
        raise ValueError('Unsupported profile value')
    def table(items, prefix=''):
        if prefix: lines.append('[' + prefix + ']')
        for key, val in items.items():
            if not isinstance(val, dict): lines.append(key + ' = ' + value(val))
        lines.append('')
        for key, val in items.items():
            if isinstance(val, dict): table(val, prefix + '.' + key if prefix else key)
    table(data)
    return '\n'.join(lines)


def snapshot_profile(source, settings, directory, profiles):
    if not isinstance(settings, dict) or set(settings) - {'models', 'components', 'parameters', 'initial_harness', 'full_evaluation', 'benchmark', 'dataset'}:
        raise ValueError('Unknown task settings')
    loaded = load_profile(source)
    raw = tomllib.loads(Path(source).read_text())
    for key in ('benchmark', 'initial_harness', 'agent_config', 'env_file', 'submission'):
        raw[key] = loaded[key]
    if 'benchmark' in settings:
        raw['benchmark'] = selected_benchmark(settings['benchmark'])
    if 'models' in settings:
        selected = settings['models']
        if not isinstance(selected, dict) or set(selected) != {'execution', 'analysis'}:
            raise ValueError('Select execution and analysis models')
        available = connections(profiles)
        raw['models'] = {}
        for role, identity in selected.items():
            if identity == 'business_agent' and role == 'execution' and loaded['agent_config']:
                raw['models'][role] = {'managed_by': 'business_agent'}
                continue
            if not isinstance(identity, str) or ':' not in identity:
                raise ValueError('Unknown model choice')
            connection_id, model = identity.split(':', 1)
            if connection_id not in available:
                raise ValueError('Unknown model connection')
            conn = available[connection_id]
            if not model.startswith(conn['provider'] + '/'):
                raise ValueError('Model provider does not match the connection')
            raw['models'][role] = {**{k: v for k, v in conn['config'].items() if k != 'base_url_env'}, 'base_url': conn['base'], 'model': model}
            # Connections can originate in a different profile's private env.
            # Use only refs resolvable by this task's env_file, never copy keys.
            env = profile_environment(loaded)
            if not env.get(conn['config']['api_key_env']):
                raise ValueError('Selected model credential is unavailable in this task environment')
    if 'components' in settings:
        from harnesslens.harnesses.component_policy import normalize_policy
        raw['components'] = normalize_policy(settings['components'])
    parameters = settings.get('parameters', {})
    if not isinstance(parameters, dict) or set(parameters) - set(PARAMETERS):
        raise ValueError('Unknown evolution parameters')
    for key, number in parameters.items():
        _, _, minimum, maximum = PARAMETERS[key]
        if type(number) is not int or not minimum <= number <= maximum:
            raise ValueError(f'{key} must be an integer between {minimum} and {maximum}')
    raw.setdefault('environment', {}).update(parameters)
    # The generic rollout cap must also bound the CRM adapter's own cap.
    if 'HAI_MAX_ROLLOUT_CONCURRENCY' in parameters:
        raw['environment']['HAI_CRM_MAX_CONCURRENCY'] = parameters['HAI_MAX_ROLLOUT_CONCURRENCY']
        raw['environment']['HAI_FDABENCH_MAX_CONCURRENCY'] = parameters['HAI_MAX_ROLLOUT_CONCURRENCY']
    if 'HAI_CRM_TIMEOUT_S' in parameters:
        raw['environment']['HAI_FDABENCH_TIMEOUT_S'] = parameters['HAI_CRM_TIMEOUT_S']
    if 'initial_harness' in settings:
        if not isinstance(settings['initial_harness'], str): raise ValueError('initial_harness must be a path')
        from .library import selected_harness
        raw['initial_harness'] = selected_harness(settings['initial_harness'])
    if 'full_evaluation' in settings:
        if type(settings['full_evaluation']) is not bool: raise ValueError('full_evaluation must be boolean')
        raw['full_evaluation'] = settings['full_evaluation']
    if 'dataset' in settings or 'dataset' in raw:
        from harnesslens.benchmarks.selection import normalize_dataset, resolve_dataset
        incoming=settings.get('dataset',raw.get('dataset',{}))
        if 'dataset' in settings and (not isinstance(incoming,dict) or 'frozen' in incoming):
            raise ValueError('Choose dataset counts and domain; task IDs are generated by the server')
        choice=normalize_dataset(incoming)
        frozen=resolve_dataset(raw['benchmark'],choice,mode=raw.get('mode','train'),full_evaluation=raw.get('full_evaluation',False))
        raw['dataset']={**choice,'frozen':frozen}
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    path = directory / 'profile.toml'
    try:
        path.write_text(dump_toml(raw))
        path.chmod(0o600)
        profile = load_profile(path)
        # Validate complete settings before preserving the draft. This never calls a model.
        if profile.get('readiness', 'ready') == 'ready':
            from .config import invocation
            invocation(profile, 'configuration-check')
    except BaseException:
        path.unlink(missing_ok=True)
        directory.rmdir()
        raise
    return path
