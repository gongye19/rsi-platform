"""Discover project-owned benchmark entries and reusable Harness snapshots."""
import json
from pathlib import Path
import re
import tomllib


def project_root(root=None):
    if root is not None:
        return Path(root).resolve()
    from .config import ROOT
    return ROOT


def benchmark_entries(root=None):
    root = project_root(root)
    result = []
    from harnesslens.benchmarks.cell_config import _ALIASES
    for path in sorted((root / 'benchmarks').glob('*/benchmark.toml')):
        if path.is_symlink() or path.parent.is_symlink() or not re.fullmatch(r'[a-z][a-z0-9_-]*', path.parent.name):
            continue
        raw = tomllib.loads(path.read_text())
        if raw.get('id') != path.parent.name:
            raise ValueError(f'Benchmark ID must match its directory: {path.parent.name}')
        if raw.get('schema') == 'rsi.benchmark.v1':
            adapter = raw.get('adapter')
            if adapter not in _ALIASES or set(raw) - {'schema', 'id', 'name', 'adapter'}:
                raise ValueError(f'Invalid builtin benchmark entry: {path.parent.name}')
            source = adapter
        elif raw.get('schema') == 'harnesslens.business-benchmark.v1':
            if raw.get('tasks')!='data/tasks.jsonl' or (raw.get('grader')=='python' and raw.get('grader_file')!='scorer.py'):
                raise ValueError('Standard benchmarks use data/tasks.jsonl and optional scorer.py')
            source = str(path.resolve())
        else:
            raise ValueError(f'Unsupported benchmark entry: {path.parent.name}')
        result.append({'id': raw['id'], 'label': raw.get('name', raw['id']), 'source': source})
    return result


def harness_entries(root=None):
    root = project_root(root)
    from harnesslens.harnesses.initial_harness import load_initial_harness
    result = []
    for directory in sorted((root / 'harnesses').glob('*')):
        if not directory.is_dir() or directory.is_symlink() or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', directory.name):
            continue
        index = directory / 'library.json'
        if index.is_file():
            raw = json.loads(index.read_text())
            if raw.get('schema') != 'rsi.harness-library.v1':
                continue
            for version, row in raw.get('versions', {}).items():
                path = (directory / row['path']).resolve()
                if not path.is_relative_to(directory.resolve()) or not path.is_file():
                    continue
                result.append({'id': f'harness:{directory.name}/{version}',
                    'label': f'{directory.name} / {version}' + (' · Selected' if raw.get('selected_version') == version else ''),
                    'path': str(path)})
        else:
            source = directory / 'package.json' if (directory / 'package.json').is_file() else directory
            if not any(directory.iterdir()):
                continue
            try:
                load_initial_harness(source)
            except (ValueError, OSError, KeyError):
                continue
            result.append({'id': 'harness:' + directory.name, 'label': directory.name, 'path': str(source.resolve())})
    return result


def selected_harness(value, root=None):
    if not isinstance(value, str):
        raise ValueError('Choose an initial Harness')
    if not value:
        return ''
    choices = harness_entries(root)
    match = next((row for row in choices if value in {row['id'], row['path']}), None)
    if match:
        return match['path']
    if value.startswith('harness:'):
        raise ValueError('The selected Harness is no longer in harnesses/')
    # Existing CLI/profile paths remain compatible; the UI offers library choices only.
    from harnesslens.harnesses.initial_harness import load_initial_harness
    path = str(Path(value).expanduser().resolve())
    load_initial_harness(path)
    return path
