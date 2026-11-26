"""Lightweight synthetic checks; no benchmark downloads or model requests."""

import hashlib
import io
import json
from pathlib import Path
import socket
import sqlite3
import threading
import urllib.error
import urllib.request
import zipfile

import pytest

from harnesslens.benchmarks.fdabench import data, download
from harnesslens.benchmarks.fdabench.judge import Judge, parse_score
from harnesslens.benchmarks.fdabench.tools import ToolService
from harnesslens.benchmarks.cell_config import benchmark_config
from harnesslens.benchmarks.benchmark_splits import load_benchmark_split
from harnesslens.harnesses.native_harness_driver import summarize_records
from harnesslens.evolution.experience import _comparison_outcome_summary
from harnesslens.evolution.main_agent import (
    outcome_improved,
    _attributable_positive_task_ids,
)
from harnesslens.evolution.controller import reference_metrics_from_comparison_index

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def assets(tmp_path):
    (tmp_path / "databases").mkdir()
    db = tmp_path / "databases/demo.sqlite"
    with sqlite3.connect(db) as c:
        c.execute("create table sales(amount integer)")
        c.executemany("insert into sales values (?)", [(3,), (7,)])
    index = tmp_path / "documents.sqlite"
    with sqlite3.connect(index) as c:
        c.execute(
            "create virtual table chunks using fts5(path unindexed,page unindexed,text,tokenize='porter unicode61')"
        )
        c.execute(
            "insert into chunks values (?,?,?)",
            ("reports/example.pdf", 1, "Revenue grew by ten percent"),
        )
    return tmp_path, db, index


def test_registry_and_frozen_split():
    config = benchmark_config(ROOT, "fdabench")
    split = load_benchmark_split("fdabench")
    assert config.primary_metric == "mean_reward" and config.kind == "fdabench"
    assert (
        len(split.train) == 70
        and len(split.test) == 35
        and not set(split.train) & set(split.test)
    )
    manifest = download.asset_manifest()
    assert (
        sum(d["path"].lower().endswith(".pdf") for d in manifest["documents"]) == 1418
        and len(manifest["databases"]) == 16
    )
    assert all(d.get("sha256") or d.get("git_blob") for d in manifest["documents"])
    from harnesslens.benchmarks.adapters import benchmark_adapter

    adapter = benchmark_adapter(ROOT, "fdabench")
    assert all(p.is_file() for p in adapter.source_files())
    assert "fdabench" in {
        r["id"]
        for r in __import__(
            "harnesslens.service.settings", fromlist=["benchmark_choices"]
        ).benchmark_choices()
    }


@pytest.mark.parametrize(
    "statement",
    [
        "delete from sales",
        "attach database ':memory:' as other",
        "select load_extension('a')",
        "pragma user_version=3",
    ],
)
def test_sql_is_read_only(assets, statement):
    with pytest.raises(sqlite3.DatabaseError):
        data.sql_query(assets[1], statement)
    assert data.sql_query(assets[1], "select sum(amount) from sales")["rows"] == [(10,)]


def test_document_tools(assets):
    found = data.search(assets[2], 'revenue OR NOT "')
    assert found["results"][0]["path"] == "reports/example.pdf"
    assert (
        data.read_document(assets[2], "../../evaluation/references.jsonl")["chunks"]
        == []
    )
    assert data.read_document(assets[2], "reports/example.pdf")["chunks"] == [
        "Revenue grew by ten percent"
    ]


def test_scoped_service_and_web_budget(assets, monkeypatch):
    import harnesslens.benchmarks.fdabench.tools as module

    monkeypatch.setattr(module, "web_search", lambda q: {"results": []})
    root, _, index = assets
    service = ToolService(root, {"task": {"db": "demo"}}, index, root / "logs")
    try:
        token = service.register("task", "trial-one")

        def post(value, credential=token):
            req = urllib.request.Request(
                service.url,
                json.dumps(value).encode(),
                {"Authorization": "Bearer " + credential},
            )
            return json.load(urllib.request.urlopen(req, timeout=5))

        assert post(
            {"tool": "sql", "value": "select sum(amount) from sales", "task": "other"}
        )["rows"] == [[10]]
        with pytest.raises(urllib.error.HTTPError):
            post({"tool": "schema"}, "wrong")
        for n in range(15):
            assert (
                post({"tool": "web_search", "value": "query", "trial_id": str(n)})[
                    "status"
                ]
                == "success"
            )
        assert (
            post({"tool": "web_search", "value": "query", "trial_id": "new"})["status"]
            == "error"
        )
        service.revoke(token)
        with pytest.raises(urllib.error.HTTPError):
            post({"tool": "schema"})
    finally:
        service.close()


def judge_fixture(tmp_path, monkeypatch, requester):
    import harnesslens.benchmarks.fdabench.judge as module

    monkeypatch.setattr(
        module,
        "judge_connection",
        lambda: {
            "model": "test/judge",
            "base_url": "https://example.invalid/v1",
            "api": "responses",
            "api_key": "test-only",
        },
    )
    (tmp_path / "evaluation").mkdir(exist_ok=True)
    reference = {
        "task_id": "t",
        "ground_truth_report": "private answer",
        "rubric": {
            "evaluation_dimensions": {
                "SQL_ACCURACY": {"weight": 0.5},
                "EXTERNAL_INTEGRATION": {"weight": 0.2},
                "LOGICAL_REASONING": {"weight": 0.2},
                "COMPLETENESS": {"weight": 0.1},
            }
        },
    }
    (tmp_path / "evaluation/references.jsonl").write_text(json.dumps(reference) + "\n")
    return Judge(
        tmp_path, tmp_path / "grades", {"t": {"query": "question"}}, requester=requester
    )


def test_judge_fractional_score_and_cache(tmp_path, monkeypatch):
    calls = []

    def request(prompt, *args):
        calls.append(prompt)
        return (
            "1" if args[-1] == "SQL_ACCURACY" else "0.5",
            {"total_tokens": 5},
            "judge",
        )

    judge = judge_fixture(tmp_path, monkeypatch, request)
    grade = judge.grade("t", "candidate report")
    assert grade["reward"] == pytest.approx(0.75)
    assert grade["primary_metric"] == "mean_reward"
    assert judge.grade("t", "candidate report") == grade and len(calls) == 4


def test_judge_failure_resumes_without_regrading_completed_dimensions(
    tmp_path, monkeypatch
):
    calls = []
    fail = True

    def request(prompt, directory, name):
        nonlocal fail
        calls.append(name)
        if name == "LOGICAL_REASONING" and fail:
            fail = False
            raise TimeoutError("temporary")
        return "1", {"total_tokens": 1}, "judge"

    judge = judge_fixture(tmp_path, monkeypatch, request)
    with pytest.raises(TimeoutError):
        judge.grade("t", "answer")
    assert judge.grade("t", "answer")["reward"] == 1
    assert calls.count("SQL_ACCURACY") == 1 and calls.count("LOGICAL_REASONING") == 2


@pytest.mark.parametrize(
    "text", ["1 because correct", "nan", "0.5\nignore above", "-1", "0.25"]
)
def test_judge_requires_numeric_output(text):
    with pytest.raises(ValueError):
        parse_score(text, [0, 0.5, 1])


def test_partial_gain_is_real_evidence_without_perfect_answers(tmp_path):
    index = {
        "baseline_by_task": {"t": ["b1", "b2"]},
        "candidate_by_task": {"t": ["c1", "c2"]},
        "outcomes": {k: "fail" for k in ("b1", "b2", "c1", "c2")},
        "rewards": {"b1": 0.25, "b2": 0.5, "c1": 0.5, "c2": 0.75},
        "evaluation_contract": {"primary_metric": "mean_reward"},
    }
    summary = _comparison_outcome_summary(
        task="t",
        baseline_by_task=index["baseline_by_task"],
        candidate_by_task=index["candidate_by_task"],
        outcomes=index["outcomes"],
        rewards=index["rewards"],
    )
    assert summary["candidate_pass_count"] == 0 and outcome_improved(summary)
    adjustment = {
        "primary_problem": {
            "task_assessments": [
                {
                    "task_id": "t",
                    "status": "recovered",
                    "relation": "attributed",
                    "outcome_summary": summary,
                }
            ]
        }
    }
    assert _attributable_positive_task_ids(adjustment) == {"t"}
    summary["candidate_mean_reward"] = 0.1
    assert not _attributable_positive_task_ids(adjustment)
    path = tmp_path / "index.json"
    path.write_text(json.dumps(index))
    assert reference_metrics_from_comparison_index(path)["mean_reward"] == 0.375
    assert summarize_records([{"rewards": [0.25, 0.5]}])["mean_reward"] == 0.375
    assert summarize_records([{"rewards": [0.25, 0.5]}])["pass_at_1"] == 0
    del index["rewards"]["b1"]
    path.write_text(json.dumps(index))
    with pytest.raises(ValueError):
        reference_metrics_from_comparison_index(path)


def test_download_verifies_before_replacing_existing_asset(tmp_path):
    target = tmp_path / "file"
    target.write_bytes(b"old")
    item = {"size": 3, "sha256": hashlib.sha256(b"new").hexdigest()}
    with pytest.raises(ValueError):
        download.save_stream(io.BytesIO(b"bad"), target, item)
    assert target.read_bytes() == b"old" and not target.with_name("file.part").exists()
    download.save_stream(io.BytesIO(b"new"), target, item)
    assert target.read_bytes() == b"new"
    with pytest.raises(ValueError):
        download.safe_target(tmp_path, "../private")


def test_download_redirect_drops_cross_host_credentials():
    req = urllib.request.Request(
        "https://huggingface.co/source", headers={"Authorization": "Bearer synthetic"}
    )
    redirected = download.SafeRedirect().redirect_request(
        req, None, 302, "", {}, "https://cdn.example/file"
    )
    assert redirected.get_header("Authorization") is None
    with pytest.raises(ValueError):
        download.SafeRedirect().redirect_request(
            req, None, 302, "", {}, "http://cdn.example/file"
        )


def test_range_reader_and_nested_zip(monkeypatch):
    inner = io.BytesIO()
    with zipfile.ZipFile(inner, "w") as z:
        z.writestr("demo.sqlite", b"sqlite fixture")
    outer = io.BytesIO()
    with zipfile.ZipFile(outer, "w") as z:
        z.writestr("nested.zip", inner.getvalue(), compress_type=zipfile.ZIP_STORED)
    raw = outer.getvalue()

    class Response(io.BytesIO):
        pass

    def fake(url, headers):
        start, end = map(int, headers["Range"].removeprefix("bytes=").split("-"))
        response = Response(raw[start : end + 1])
        response.status = 206
        response.headers = {"Content-Range": f"bytes {start}-{end}/{len(raw)}"}
        return response

    monkeypatch.setattr(download, "open_url", fake)
    with download.archives("https://example.invalid/file") as archives:
        assert archives[1].read("demo.sqlite") == b"sqlite fixture"


def test_short_loopback_gateway_socket_is_usable_and_removed():
    from harnesslens.infrastructure.loopback_gateway import host_gateway

    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]

    def echo():
        conn, _ = listener.accept()
        with conn:
            conn.sendall(conn.recv(10))

    thread = threading.Thread(target=echo, daemon=True)
    thread.start()
    with host_gateway([port]) as root:
        assert len(str(root / f"{port}.sock")) < 100
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.connect(str(root / f"{port}.sock"))
            client.sendall(b"ok")
            assert client.recv(10) == b"ok"
    thread.join(timeout=2)
    listener.close()
    assert not root.exists()

def test_grading_checkpoint_reuses_answer_and_rejects_changed_config(tmp_path,monkeypatch):
    from harnesslens.evaluation import native_benchmark as native
    from harnesslens.benchmarks.adapters import BusinessLimits,sha
    from harnesslens.harnesses.native_harness_driver import stable_hash
    from harnesslens.core.artifacts import write_json
    manifest={'files':[]};limits=BusinessLimits();signature={'environment':'fixed'}
    trace=tmp_path/'api_calls.jsonl'
    trace.write_text(json.dumps({'request':{'messages':[]},'response':{'choices':[]},'upstream_status':200})+'\n')
    (tmp_path/'answer.txt').write_text('cached report')
    identity=stable_hash({'environment':signature,'task':'t','slot':0,'scope':'TRAIN','manifest':manifest,'limits':limits.to_dict()})
    write_json(tmp_path/'execution.json',{'identity_sha256':identity,'api_trace_sha256':sha(trace),'answer_sha256':sha(tmp_path/'answer.txt'),'answer':'cached report','infrastructure_error':True})
    calls=[]
    class Adapter:
        def grade(self,task,answer):
            calls.append(answer)
            if len(calls)==1:raise TimeoutError('judge unavailable')
            return {'reward':.75,'rs':.75,'primary_metric':'mean_reward','validator_sha256':'validator'}
    monkeypatch.setattr(native,'_start_proxy',lambda **kw:pytest.fail('solver must not run again'))
    args=(Adapter(),{},tmp_path,'t',0,0,'TRAIN','v0',manifest,limits,signature)
    with pytest.raises(TimeoutError):native.run_trial(*args)
    assert native.run_trial(*args)['reward']==.75
    assert native.run_trial(*args)['reward']==.75 and len(calls)==2
    with pytest.raises(ValueError,match='configuration changed'):native.run_trial(*args[:-1],{'environment':'changed'})
    (tmp_path/'answer.txt').write_text('tampered')
    with pytest.raises(ValueError,match='answer changed'):native.run_trial(*args)

def test_native_attempts_are_bounded_and_preserve_failed_workspace(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from harnesslens.evaluation import native_benchmark as native
    from harnesslens.benchmarks.adapters import BusinessLimits
    from harnesslens.core.artifacts import write_json
    import harnesslens.harnesses.opencode_execution as extensions
    monkeypatch.setenv('HAI_NATIVE_EXECUTION_ATTEMPTS','2')
    calls=[]
    class Adapter:
        cell='synthetic';max_concurrency=1
        def limits(self):return BusinessLimits()
        def fingerprint(self):return {'fixed':True}
        def split(self):return SimpleNamespace(train=('t',),test=('heldout',))
        def benchmark_config(self):return SimpleNamespace(primary_metric='mean_reward')
        @contextmanager
        def execution_context(self):yield {}
        def prepare_task(self,workspace,*args):
            (workspace/'source').mkdir();(workspace/'source/client.py').write_text('fixed');(workspace/'output').mkdir()
            return {'prompt':'question','ports':[]}
        def grade(self,*args):return {'reward':.5,'validator_sha256':'validator'}
    def prepare(root,*args):
        workspace=root/'workspace';home=workspace/'candidate-home';home.mkdir()
        (workspace/'AGENTS.md').write_text('rules');(workspace/'opencode.json').write_text('{}')
        write_json(workspace/'.runtime/harnesslens/settings.json',{'protected_files':[]})
        return home,{},{}
    @contextmanager
    def isolate(command,*args):yield command
    def process(command,*,cwd,**kwargs):
        calls.append(cwd)
        if len(calls)==1:raise TimeoutError('transient execution failure')
        event={'request':{'messages':[{'role':'user','content':'question'}]},'response':{'choices':[{'message':{'role':'assistant','content':'report'},'finish_reason':'stop'}]},'usage':{'total_tokens':3},'upstream_status':200}
        (cwd.parent/'api_calls.jsonl').write_text(json.dumps(event)+'\n');(cwd/'output/answer.txt').write_text('report')
        return '', '', 0
    monkeypatch.setattr(native,'prepare_harness',prepare)
    monkeypatch.setattr(native,'isolated_command',isolate)
    monkeypatch.setattr(native,'_start_proxy',lambda **kw:(None,1234))
    monkeypatch.setattr(native,'run_process',process)
    monkeypatch.setattr(native,'refresh_report',lambda *a:[])
    monkeypatch.setattr(native,'executable',lambda:tmp_path/'bin/opencode')
    monkeypatch.setattr(native,'model',lambda:'test/model')
    monkeypatch.setattr(extensions,'install_plugin_helpers',lambda p:p)
    monkeypatch.setattr(native.time,'sleep',lambda _:None)
    result=native.run_batch(adapter=Adapter(),run_root=tmp_path,scope='TRAIN',harness='opencode',harness_version='v0',harness_manifest={'files':[]},task_repeats={'t':1},pairing_offsets={},max_concurrency=1)
    assert result['metrics']['mean_reward']==.5 and len(calls)==2
    assert len(list(tmp_path.glob('trials/*/trial_0000/failed_attempts/attempt-0001/workspace')))==1

def test_remote_zip_reader_handles_stored_nested_archive(monkeypatch):
    inner=io.BytesIO()
    with zipfile.ZipFile(inner,'w',compression=zipfile.ZIP_DEFLATED) as archive:archive.writestr('db.sqlite',b'synthetic database')
    outer=io.BytesIO()
    with zipfile.ZipFile(outer,'w',compression=zipfile.ZIP_STORED) as archive:archive.writestr('databases.zip',inner.getvalue())
    content=outer.getvalue();ranges=[]
    def open_range(url,*,headers=None,**kwargs):
        begin,end=map(int,headers['Range'].removeprefix('bytes=').split('-'));ranges.append((begin,end))
        response=io.BytesIO(content[begin:end+1]);response.status=206;response.headers={'Content-Range':f'bytes {begin}-{end}/{len(content)}'}
        return response
    monkeypatch.setattr(download,'open_url',open_range)
    with download.archives('https://example.invalid/data.zip') as sources:
        assert len(sources)==2 and sources[1].read('db.sqlite')==b'synthetic database'
    assert ranges and all(end-begin+1<=4*1024**2 for begin,end in ranges)

def test_judge_proxy_override_does_not_mutate_execution_environment(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import os
    from harnesslens.core import model_config
    from harnesslens.harnesses import opencode_runtime
    captured={}
    monkeypatch.setattr(model_config,'proxy_environment',lambda role:{'DEEPSEEK_API_KEY':'analysis-test-key','DEEPSEEK_BASE_URL':'https://analysis.invalid/v1'})
    def popen(*args,**kwargs):
        captured.update(kwargs['env']);return SimpleNamespace(stdout=io.StringIO('PORT=12345\n'))
    monkeypatch.setattr(opencode_runtime.subprocess,'Popen',popen)
    previous=os.environ.get('DEEPSEEK_API_KEY')
    _,port=opencode_runtime._start_proxy(run_root=tmp_path,call_id='judge',connection_override={'model':'provider/judge-override','api_key':'judge-test-key','base_url':'https://judge.invalid/v1','api':'responses'})
    assert port==12345 and captured['DEEPSEEK_API_KEY']=='judge-test-key' and captured['HAI_PROXY_API']=='responses' and captured['HAI_PROXY_MODEL']=='judge-override'
    assert os.environ.get('DEEPSEEK_API_KEY')==previous

def test_public_task_projection_and_configuration_are_generic(monkeypatch,tmp_path):
    from harnesslens.benchmarks.fdabench.adapter import FDABenchAdapter
    from harnesslens.service.config import load_profile
    adapter=FDABenchAdapter(ROOT);task=adapter.split().train[0]
    adapter._tasks={task:{'task_id':task,'db':'example','query':'public question','question_type':'report','ground_truth_report':'PRIVATE','rubric':{'private':True}}}
    assert 'PRIVATE' not in json.dumps(adapter.explorer_input([task]))
    with pytest.raises(ValueError):adapter.explorer_input([adapter.split().test[0]])
    profile=load_profile(ROOT/'configs/experiments/fdabench.toml')
    assert profile['benchmark']=='fdabench' and len(profile['components']['allowed'])==16
    from harnesslens.benchmarks.jsonl_adapter import JsonlAdapter
    tasks=tmp_path/'tasks.jsonl';tasks.write_text(json.dumps({'id':'a','question':'q','answer':'a'})+'\n'+json.dumps({'id':'b','question':'q','answer':'b'})+'\n')
    descriptor=tmp_path/'continuous.toml';descriptor.write_text('schema="harnesslens.business-benchmark.v1"\nid="synthetic_continuous"\ntasks="tasks.jsonl"\ntrain=["a"]\ntest=["b"]\nprimary_metric="mean_reward"\n')
    assert JsonlAdapter(ROOT,descriptor).benchmark_config().primary_metric=='mean_reward'

def test_judge_stops_proxy_and_isolates_trace_attempts(tmp_path,monkeypatch):
    import httpx
    from types import SimpleNamespace
    from harnesslens.harnesses import opencode_runtime
    stopped=[];roots=[];process=object()
    judge=judge_fixture(tmp_path,monkeypatch,lambda *_:None)
    def start(**kwargs):
        root=kwargs['run_root'];roots.append(root)
        (root/'api_calls.jsonl').write_text(json.dumps({'request':{},'response':{},'upstream_status':200})+'\n')
        return process,1234
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,*args,**kwargs):
            return SimpleNamespace(raise_for_status=lambda:None,json=lambda:{'status':'completed','output':[{'content':[{'type':'output_text','text':'0.5'}]}],'usage':{'input_tokens':10,'output_tokens':1,'total_tokens':11},'model':'judge'})
    monkeypatch.setattr(opencode_runtime,'_start_proxy',start)
    monkeypatch.setattr(opencode_runtime,'_stop_process',lambda p:stopped.append(p))
    monkeypatch.setattr(httpx,'Client',Client)
    for _ in range(2):assert judge._request('prompt',tmp_path,'DIM')[0]=='0.5'
    assert stopped.count(process)==2 and roots[0]!=roots[1]

def test_history_chart_uses_continuous_score(tmp_path,monkeypatch):
    from harnesslens.service import history
    monkeypatch.setattr(history,'ROOT',tmp_path)
    root=tmp_path/'runs/train/fda/baseline';root.mkdir(parents=True)
    (root/'bootstrap_event.json').write_text(json.dumps({'metrics':{'primary_metric':'mean_reward','mean_reward':.625,'pass_at_1':0,'trial_count':2}}))
    assert history.history('fda')['bundles'][0]['metrics']['score']==.625

def test_launch_snapshot_keeps_path_overrides_through_train_and_test(tmp_path,monkeypatch,model_tables):
    from scripts import prepare_fdabench
    from harnesslens.service.config import load_profile,profile_environment
    monkeypatch.setattr(prepare_fdabench,'ROOT',tmp_path)
    private=tmp_path/'private.env';private.write_text('HAI_FDABENCH_ROOT=/old/location\n')
    source=tmp_path/'profile.toml';source.write_text('schema="harnesslens.experiment.v1"\nbenchmark="fdabench"\nenv_file="private.env"\n'+model_tables)
    path=prepare_fdabench.launch_profile(source,'test',data_root='/new/location',index='/new/index.sqlite')
    snapshot=load_profile(path);env=profile_environment(snapshot)
    assert env['HAI_FDABENCH_ROOT']=='/new/location' and env['HAI_FDABENCH_INDEX']=='/new/index.sqlite'
    assert snapshot['env_file']==str(private) and 'execution-test-only' not in path.read_text()

def test_linux_command_unshares_network_and_mounts_only_scoped_gateway(tmp_path,monkeypatch):
    from harnesslens.evaluation import native_benchmark as native
    from harnesslens.infrastructure import process_isolation
    from harnesslens.harnesses import opencode_execution
    workspace=tmp_path/'workspace';(workspace/'.runtime').mkdir(parents=True)
    fixed=workspace/'source';fixed.mkdir();captured={}
    monkeypatch.setattr(native.sys,'platform','linux')
    monkeypatch.setattr(native,'executable',lambda:tmp_path/'runtime/bin/opencode')
    monkeypatch.setattr(opencode_execution,'install_plugin_helpers',lambda p:p)
    def builder(command,**kwargs):
        captured.update(kwargs);return ['bwrap','--bind',str(workspace),str(workspace),'--',*command]
    monkeypatch.setattr(process_isolation,'bubblewrap_command',builder)
    with native.isolated_command(['opencode','run'],workspace,[12345],[fixed]) as command:
        assert '--unshare-net' in command
        assert ['--ro-bind',str(fixed),str(fixed)]==command[command.index('--ro-bind'):command.index('--ro-bind')+3]
        gateway=captured['read_only_roots'][-1]
        assert (gateway/'12345.sock').exists() and len(str(gateway/'12345.sock'))<100
        assert tmp_path not in captured['read_only_roots']
    assert not gateway.exists()
