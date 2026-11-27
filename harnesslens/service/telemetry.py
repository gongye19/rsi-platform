"""Observed usage and progress only: no prompts, estimates, or extra model calls.

Full traces remain the source of truth. New proxies emit compact sidecars; older
runs are read incrementally once and cached by inode/offset. Copied trajectories
and harness snapshots are excluded to avoid double-counting requests.
"""
from datetime import datetime
from pathlib import Path
import json
import os
import re
import threading
import time

from harnesslens.core.artifacts import write_json
from .history import read

_LOCK = threading.Lock()
_FILES = {}
_RUNS = {}
_SKIP = {'workspace', 'baseline_workspace', 'rollout_evidence', 'trajectories',
         'versions_percell', 'node_modules', '.git', '.oc_data', '.oc_cache',
         '.oc_config', '.runtime', '__pycache__', 'harness'}
_TERMINAL = {'succeeded', 'failed', 'interrupted', 'stopped'}


def timestamp(value):
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).timestamp()
        except ValueError:
            pass
    return None


def empty_usage():
    return dict(requests=0, input_tokens=0, output_tokens=0, total_tokens=0,
                cached_input_tokens=0, missing_usage=0, failed_requests=0,
                request_seconds=0.0, timed_requests=0, retries=0, models=[])


def add_usage(total, row):
    if row.get('event'):
        total['retries'] += int(row['event'] == 'upstream_retry')
        return
    total['requests'] += 1
    usage = row.get('usage') or {}
    inp = usage.get('input_tokens', usage.get('prompt_tokens'))
    out = usage.get('output_tokens', usage.get('completion_tokens'))
    amount = usage.get('total_tokens')
    if amount is None and type(inp) is int and type(out) is int:
        amount = inp + out
    if type(amount) is not int or amount < 0:
        total['missing_usage'] += 1
    else:
        total['total_tokens'] += amount
        total['input_tokens'] += inp if type(inp) is int and inp >= 0 else 0
        total['output_tokens'] += out if type(out) is int and out >= 0 else 0
        details = usage.get('input_tokens_details') or usage.get('prompt_tokens_details') or {}
        cached = row.get('cached_input_tokens', details.get('cached_tokens', usage.get('prompt_cache_hit_tokens', 0)))
        total['cached_input_tokens'] += cached if type(cached) is int and cached >= 0 else 0
    total['failed_requests'] += int(bool(row.get('failed') or row.get('error') or row.get('upstream_status', 200) >= 400))
    seconds = row.get('seconds')
    if isinstance(seconds, (int, float)) and seconds >= 0:
        total['request_seconds'] += seconds
        total['timed_requests'] += 1
    if row.get('model') and row['model'] not in total['models']:
        total['models'].append(row['model'])


def trace_summary(path):
    """Only complete appended JSONL lines are committed, including after truncation."""
    stat = path.stat()
    old = _FILES.get(str(path))
    identity = (stat.st_dev, stat.st_ino)
    if not old or old['identity'] != identity or stat.st_size < old['offset'] or (stat.st_size == old['offset'] and stat.st_mtime_ns != old['mtime']):
        old = dict(identity=identity, offset=0, mtime=0, usage=empty_usage(), latest=None, first=None)
    with path.open('rb') as stream:
        stream.seek(old['offset'])
        while line := stream.readline():
            if not line.endswith(b'\n'):
                break
            old['offset'] = stream.tell()
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if not isinstance(row, dict):
                continue
            add_usage(old['usage'], row)
            at = timestamp(row.get('finished_at') or row.get('ts'))
            start = timestamp(row.get('ts'))
            if at: old['latest'] = max(old['latest'] or 0, at)
            if start: old['first'] = min(old['first'] or start, start)
    old['mtime'] = stat.st_mtime_ns
    _FILES[str(path)] = old
    return old


def observed_files(roots):
    seen = set()
    for root in roots:
        if not root.is_dir():
            continue
        for directory, folders, names in os.walk(root, followlinks=False):
            folders[:] = [f for f in folders if f not in _SKIP and not f.startswith('.') and not (Path(directory)/f).is_symlink()]
            parent = Path(directory)
            if parent.is_symlink(): continue
            for name in ('api_usage.jsonl' if 'api_usage.jsonl' in names else 'api_calls.jsonl', 'progress.json'):
                path = parent / name
                if name in names and not path.is_symlink() and str(path.resolve()) not in seen:
                    seen.add(str(path.resolve()))
                    yield path


def snapshot(repo, job, *, now=None):
    repo = Path(repo)
    now = time.time() if now is None else now
    key = str(repo), job['id']
    with _LOCK:
        cached = _RUNS.get(key)
        signature = job['state'], job.get('updated')
        if cached and cached[1] == signature and (now - cached[0] < 2 or job['state'] == 'succeeded'):
            return cached[2]
        value = _snapshot(repo, job, now)
        _RUNS[key] = now, signature, value
        return value


def _snapshot(repo, job, now):
    identity = job['id']
    train = repo/'runs/train'/identity
    local = repo/'runs/local_experiments'/identity
    result = read(local/'result.json', {})
    test_id = result.get('test_run_id', identity+'-test')
    # Read only this experiment. Never recursively include continuation/source runs.
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,95}', test_id):
        test_id = identity+'-test'
    roots = [train, repo/'runs/test_baselines'/test_id, repo/'runs/test_candidates'/test_id,
             repo/'runs/test_baselines'/identity, repo/'runs/test_candidates'/identity]
    actors = {role:empty_usage() for role in ('execution','analysis','evaluation')}
    batches = []
    latest = first = None
    for path in observed_files(roots):
        if path.name == 'progress.json':
            batch = read(path, {})
            if 'total' in batch:
                batch['id'] = str(path.parent.relative_to(repo/'runs'))
                batches.append(batch)
                latest = max(latest or 0, batch.get('updated_at', 0))
            continue
        actor = 'analysis' if 'intelligent_jobs' in path.parts or 'harness_editor' in path.parts else 'evaluation' if 'judge_calls' in path.parts else 'execution'
        summary = trace_summary(path)
        for k, v in summary['usage'].items():
            if k == 'models':
                actors[actor][k] = sorted(set(actors[actor][k]) | set(v))
            else:
                actors[actor][k] += v
        if summary['latest']: latest = max(latest or 0, summary['latest'])
        if summary['first']: first = min(first or summary['first'], summary['first'])
    ledger = read(train/'creation_budget.json', {})
    jobs = ledger.get('jobs', {})
    active_jobs = [dict(id=k, started_at=timestamp(v.get('launched_at') or v.get('reserved_at')))
                   for k,v in jobs.items() if v.get('status') in {'launched','launch_claimed','reserved'}]
    checkpoint = read(train/'controller_state.json', {})
    activity = [timestamp(checkpoint.get('updated_at'))]
    for item in jobs.values():
        activity += [timestamp(item.get(k)) for k in ('launched_at','settled_at')]
    latest = max([latest or 0, *[at for at in activity if at]]) or None
    active_jobs.sort(key=lambda item:item['started_at'] or 0)
    current = max(batches, key=lambda b:b.get('updated_at', 0), default=None)
    if current and job['state'] in _TERMINAL:
        current = {**current, 'active': []}
    iteration_files = list((train/'main_agent').glob('iteration-[0-9][0-9].json'))
    numbers = [int(re.search(r'iteration-(\d+)',p.name)[1]) for p in iteration_files]
    numbers += [int(m[1]) for item in active_jobs if (m:=re.search(r'iteration-(\d+)',item['id']))]
    final = read(train/'submission/final.json', {})
    rounds = final.get('iteration_history', [])
    started = timestamp(ledger.get('created_at')) or first
    ended = timestamp(job.get('updated')) if job['state'] in _TERMINAL else None
    elapsed = max(0,(ended or now)-started) if started else None
    if not batches:
        # Historical completed runs predate batch counters; recover recorded totals.
        counts = []
        for path in [train/'baseline/bootstrap_event.json', *sorted((train/'rollout').glob('*.json'))]:
            value = read(path, {})
            metrics = value.get('metrics') or value.get('response',{}).get('metrics',{})
            counts.append(metrics.get('trial_count',0))
        for root in roots[1:]:
            for path in (root/'opencode').glob('*result.json'):
                value = read(path,{})
                metrics = value.get('metrics') or value.get('response',{}).get('metrics',{})
                counts.append(metrics.get('trial_count',0))
        historic_trials = sum(counts)
    else:
        historic_trials = 0
    telemetry = dict(schema_version=1, checked_at=now, started_at=started, finished_at=ended,
                     elapsed_seconds=elapsed, last_activity_at=latest, usage=actors,
                     progress=dict(checkpoint=checkpoint.get('stage'), iteration=max(numbers,default=0),
                                   reviewed_rounds=len(rounds) or len(list((train/'main_agent').glob('iteration-[0-9][0-9]-review.json'))),
                                   active_jobs=active_jobs if job['state'] not in _TERMINAL else [],
                                   batch=current, completed_trials=sum(b.get('completed',0) for b in batches) or historic_trials,
                                   failed_trials=sum(b.get('failed',0) for b in batches),
                                   batch_count=len(batches)))
    # This is a derived, private record. No execution evidence is modified.
    write_json(local/'telemetry.json',telemetry)
    return telemetry
