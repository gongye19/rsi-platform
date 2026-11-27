"""Telemetry is read-only observation; synthetic fixtures never call a model."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import pytest
from harnesslens.core.artifacts import write_json
from harnesslens.infrastructure.batch_progress import BatchProgress
from harnesslens.service.telemetry import snapshot, trace_summary, _FILES, _RUNS


@pytest.fixture(autouse=True)
def clear_cache():
    _FILES.clear(); _RUNS.clear()


def append(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream:
        stream.write(json.dumps(value)+'\n')


def call(amount=7):
    return dict(ts=100, model='shared-model', usage=dict(prompt_tokens=5,completion_tokens=2,total_tokens=amount))


def test_roles_test_and_failed_attempts_are_counted_without_copied_trajectories(tmp_path):
    train=tmp_path/'runs/train/test-run'
    append(train/'baseline_rollout_artifacts/benchmark_groups/x/trials/t/trial_0000/api_calls.jsonl', call())
    append(train/'rollout_artifacts/benchmark_groups/y/trials/t/trial_0000/failed_attempts/attempt-0001/api_calls.jsonl', call())
    append(train/'intelligent_jobs/editor-1/api_calls.jsonl',call())
    append(train/'rollout_evidence/copied/api_calls.jsonl',call(1000000))
    append(train/'rollout_artifacts/trajectories/copied/api_calls.jsonl',call(1000000))
    test=tmp_path/'runs/test_baselines/test-run-test/trials/a/trial_0000'
    append(test/'api_calls.jsonl',call())
    append(test/'judge_calls/x/dimension/attempt-0001/api_calls.jsonl',call())
    write_json(train/'creation_budget.json',dict(created_at='1970-01-01T00:01:30+00:00',jobs={}))
    value=snapshot(tmp_path,dict(id='test-run',state='succeeded',updated=200),now=201)
    assert value['usage']['execution']['total_tokens']==21
    assert value['usage']['analysis']['total_tokens']==7
    assert value['usage']['evaluation']['total_tokens']==7
    assert value['elapsed_seconds']==110
    assert (tmp_path/'runs/local_experiments/test-run/telemetry.json').is_file()
    assert 'request' not in value['usage']['execution']


def test_append_partial_line_retry_missing_usage_and_truncation(tmp_path):
    p=tmp_path/'api_calls.jsonl'
    append(p,call())
    assert trace_summary(p)['usage']['total_tokens']==7
    with p.open('a') as f:f.write('{"ts":101,')
    assert trace_summary(p)['usage']['requests']==1
    with p.open('a') as f:f.write('"error":"timeout"}\n')
    append(p,dict(event='upstream_retry',ts=102))
    value=trace_summary(p)['usage']
    assert value['requests']==2 and value['missing_usage']==1 and value['failed_requests']==1 and value['retries']==1
    assert value['total_tokens']==7
    p.write_text(json.dumps(call(3))+'\n')
    assert trace_summary(p)['usage']['total_tokens']==3


def test_sidecar_preferred_and_live_batch_survives_concurrent_updates(tmp_path):
    root=tmp_path/'runs/train/live/baseline_rollout_artifacts/benchmark_groups/batch'
    append(root/'trials/t/trial_0000/api_calls.jsonl',call(999999))
    append(root/'trials/t/trial_0000/api_usage.jsonl',dict(**call(),seconds=2,finished_at=102,cached_input_tokens=3))
    p=BatchProgress(root,'TRAIN','v0',{'a':2,'b':2})
    with p.trial('a',0):
        v=snapshot(tmp_path,dict(id='live',state='running',updated=90),now=103)
        assert v['progress']['batch']['active'][0]['task_id']=='a'
        assert v['usage']['execution']['total_tokens']==7
        assert v['usage']['execution']['request_seconds']==2
    def complete(n):
        with p.trial('b',n):pass
    with ThreadPoolExecutor(2) as pool:list(pool.map(complete,range(2)))
    with pytest.raises(RuntimeError):
        with p.trial('a',1):raise RuntimeError('fake timeout')
    v=snapshot(tmp_path,dict(id='live',state='running',updated=90),now=106)
    assert v['progress']['batch']['completed']==3
    assert v['progress']['batch']['failed']==1
    assert v['progress']['batch']['active']==[]
    assert v['usage']['execution']['total_tokens']==7  # No duplicate on next poll.


def test_historical_test_nested_metrics_not_reused_twice(tmp_path):
    train=tmp_path/'runs/train/history'
    write_json(train/'baseline/bootstrap_event.json',{'response':{'metrics':{'trial_count':16}}})
    write_json(tmp_path/'runs/test_baselines/history-test/opencode/baseline_result.json',{'response':{'metrics':{'trial_count':10}}})
    v=snapshot(tmp_path,dict(id='history',state='succeeded',updated=200),now=201)
    assert v['progress']['completed_trials']==26


def test_proxy_writes_compact_provider_usage_without_prompt_or_response(tmp_path,monkeypatch):
    from harnesslens.infrastructure import chat_completions_proxy as proxy
    monkeypatch.setattr(proxy,'LOG_FILE',str(tmp_path/'api_calls.jsonl'))
    row=call()
    row.update(request={'content':'private input'},response={'text':'private answer'})
    proxy._log(row)
    compact=json.loads((tmp_path/'api_usage.jsonl').read_text())
    assert compact['usage']['total_tokens']==7
    assert compact['seconds']>=0
    assert 'request' not in compact and 'response' not in compact
    assert 'private' not in json.dumps(compact)
