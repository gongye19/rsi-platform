"""Copy immutable experiment configurations into the local reusable Harness library."""
import json
from pathlib import Path
import re
from harnesslens.core.artifacts import write_json
from .initial_harness import load_initial_harness
from .opencode_package import export_package


def _sync_run_harnesses(root, run_id, initial_source=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', run_id):
        raise ValueError('Invalid Harness experiment directory')
    root = Path(root).resolve()
    directory = root / 'harnesses' / run_id
    if directory.is_symlink():
        raise ValueError('Harness library cannot be a symlink')
    index_path = directory / 'library.json'
    index = json.loads(index_path.read_text()) if index_path.exists() else {
        'schema': 'rsi.harness-library.v1', 'run_id': run_id, 'versions': {}}
    def record(version, workspace, manifest):
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', version):
            raise ValueError('Invalid Harness version')
        if version in index['versions']:
            return
        package = export_package(directory=directory / 'versions' / version, version=version,
                                 workspace=workspace, manifest=manifest)
        index['versions'][version] = {'path': str(Path(package['path']).relative_to(directory)), 'sha256': package['sha256']}
    run = root / 'runs/train' / run_id
    if 'v0' not in index['versions']:
        marker=run/'initial_harness.json'
        if marker.is_file():
            native=Path(json.loads(marker.read_text())['snapshot_path'])/'harness/opencode'
            if not native.resolve().is_relative_to(run.resolve()):
                raise ValueError('Initial snapshot must stay inside its experiment')
            record('v0',json.loads((native/'workspace.json').read_text()),json.loads((native/'manifest.json').read_text()))
        else:
            initial = load_initial_harness(initial_source)
            record('v0', initial['workspace'], initial['manifest'])
    for path in sorted(run.glob('rollout_evidence/**/versions_percell/*/*/harness/opencode/workspace.json')):
        version = path.parents[2].name
        if version in index['versions']:
            continue
        manifest_path = path.with_name('manifest.json')
        if manifest_path.is_file():
            record(version, json.loads(path.read_text()), json.loads(manifest_path.read_text()))
    final = run / 'submission/final.json'
    if final.is_file():
        selected = json.loads(final.read_text()).get('selected_version')
        if selected in index['versions']:
            index['selected_version'] = selected
    write_json(index_path, index)
    return index_path


def sync_run_harnesses(root, run_id, initial_source=None):
    import fcntl
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', run_id):
        raise ValueError('Invalid Harness experiment directory')
    parent=Path(root).resolve()/'harnesses'
    directory=parent/run_id
    if parent.is_symlink() or directory.is_symlink():
        raise ValueError('Harness library cannot be a symlink')
    directory.mkdir(parents=True,exist_ok=True)
    with (directory/'.library.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if not (directory/'library.json').exists() and any(p.name!='.library.lock' for p in directory.iterdir()):
            raise ValueError('Harness directory already exists; choose a new run ID')
        return _sync_run_harnesses(root,run_id,initial_source)
