import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

import pytest

from harnesslens.service.config import load_profile, invocation
from harnesslens.service.store import Store
from harnesslens.service.worker import Worker, process_identity
from harnesslens.service.api import server


@pytest.fixture
def profile(tmp_path, model_tables):
    path = tmp_path / "ready.toml"
    path.write_text('schema="harnesslens.experiment.v1"\nbenchmark="crm"\nreadiness="ready"\n' + model_tables)
    return path


def test_profile_blocks_draft_and_secret_in_profile(tmp_path):
    path = tmp_path / "draft.toml"
    path.write_text('schema="harnesslens.experiment.v1"\nreadiness="draft"\n')
    store = Store(tmp_path / "state")
    store.create("one", path)
    with pytest.raises(ValueError, match="Draft"):
        store.transition("one", "start")
    with pytest.raises(ValueError, match="draft"):
        invocation(load_profile(path), "one")
    path.write_text('schema="harnesslens.experiment.v1"\n[environment]\nDEEPSEEK_API_KEY="no"')
    with pytest.raises(ValueError, match="Secrets"):
        load_profile(path)


def test_transactional_queue_claim_and_fingerprint(tmp_path, profile):
    store = Store(tmp_path / "state")
    store.create("one", profile)
    store.transition("one", "start")
    results = []
    threads = [threading.Thread(target=lambda: results.append(store.claim())) for _ in range(8)]
    for thread in threads: thread.start()
    for thread in threads: thread.join()
    assert sum(result is not None for result in results) == 1
    store.update("one", state="failed")
    profile.write_text(profile.read_text() + "# changed")
    with pytest.raises(ValueError, match="changed"):
        store.transition("one", "resume")


def test_worker_real_subprocess_stop_resume_and_secret_not_persisted(tmp_path, profile):
    private = tmp_path / "private.env"
    private.write_text("DEEPSEEK_API_KEY=service-test-secret-not-for-artifacts\n")
    profile.write_text('env_file="private.env"\n' + profile.read_text())
    store = Store(tmp_path / "state")
    store.create("one", profile); store.transition("one", "start")
    worker = Worker(store)
    unrelated = subprocess.Popen([sys.executable, "-c", "import time;time.sleep(30)"], start_new_session=True)
    thread = threading.Thread(target=lambda: worker.run_once([sys.executable, "-c", "import time;time.sleep(30)"]))
    try:
        thread.start()
        deadline = time.monotonic() + 10
        while not store.get("one")["pid"] and time.monotonic() < deadline: time.sleep(.05)
        assert store.get("one")["pid"]
        store.transition("one", "stop")
        thread.join(15)
        assert not thread.is_alive()
        assert store.get("one")["state"] == "stopped"
        assert unrelated.poll() is None
        store.transition("one", "resume")
        worker.run_once([sys.executable, "-c", "print('local-validation')"])
        assert store.get("one")["state"] == "succeeded"
        assert store.get("one")["attempt"] == 2
        assert (tmp_path / "state/jobs/one/attempt-1.log").is_file()
        assert "service-test-secret" not in (tmp_path / "state/jobs/one/experiment.json").read_text()
    finally:
        unrelated.terminate(); unrelated.wait()


def test_worker_recovery_does_not_kill_reused_pid(tmp_path, profile):
    store = Store(tmp_path / "state")
    store.create("one", profile)
    store.update("one", state="running", pid=os.getpid(), identity="not-this-process")
    Worker(store).recover()
    assert store.get("one")["state"] == "interrupted"
    assert process_identity(os.getpid())


def test_api_lifecycle_auth_cursor_and_path_boundaries(tmp_path, profile):
    store = Store(tmp_path / "state")
    token = "local-test-token-1234567890123456"
    api = server(store, token, port=0, profiles=tmp_path)
    thread = threading.Thread(target=api.serve_forever, daemon=True); thread.start()
    base = f"http://127.0.0.1:{api.server_address[1]}"
    def request(path, body=None, auth=True, accept="application/json"):
        headers = {"Accept": accept}
        if auth: headers["Authorization"] = "Bearer " + token
        data = json.dumps(body).encode() if body is not None else None
        try:
            with urllib.request.urlopen(urllib.request.Request(base + path, data=data, headers=headers), timeout=5) as response:
                return response.status, response.read().decode()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read().decode()
    try:
        assert request("/health", auth=False)[0] == 200
        assert request("/v1/runs", auth=False)[0] == 401
        preview = json.loads(request("/v1/profiles?name=ready.toml")[1])
        assert preview["models"]["analysis"]["model"] == "test/analysis"
        assert "test-only" not in json.dumps(preview)
        assert request("/v1/profiles?name=../outside.toml")[0] == 400
        assert request("/v1/runs", {"profile": "../outside.toml"})[0] == 400
        assert request("/v1/runs", {"profile": "ready.toml", "run_id": "../../escape"})[0] == 400
        assert request("/v1/runs", {"profile": "ready.toml", "run_id": "api_one"})[0] == 201
        assert store.get("api_one")["state"] == "draft"
        assert request("/v1/runs", {"profile": "ready.toml", "run_id": "api_one"})[0] == 409
        assert request("/v1/runs/api_one/start", {})[0] == 200
        assert request("/v1/runs/api_one/stop", {})[0] == 200
        events = json.loads(request("/v1/runs/api_one/events")[1])
        assert len(events) == 3
        assert json.loads(request(f"/v1/runs/api_one/events?after={events[-1]['seq']}")[1]) == []
        assert "heartbeat" in request(f"/v1/runs/api_one/events?after={events[-1]['seq']}", accept="text/event-stream")[1]
        assert request("/v1/runs/api_one/artifact?root=1&path=../../../private.env")[0] == 400
        assert request("/v1/runs/api_one/history")[0] == 200
        assert request("/v1/runs", ["wrong type"])[0] == 400
    finally:
        api.shutdown(); api.server_close(); thread.join()


def test_history_uses_real_branch_parent_and_does_not_invent_component_results(tmp_path, monkeypatch):
    import importlib
    module = importlib.import_module("harnesslens.service.history")
    monkeypatch.setattr(module, "ROOT", tmp_path)
    root = tmp_path / "runs/train/branch"
    def snapshot(version, parent, text):
        directory = root / f"rollout_evidence/run/versions_percell/crm/{version}"
        path = directory / "harness/opencode"
        path.mkdir(parents=True)
        (path / "workspace.json").write_text(json.dumps({"files": [{"scope": "project", "path": "AGENTS.md", "content": text}]}))
        (directory / "lineage.json").write_text(json.dumps({"parent": parent}))
    snapshot("v1", "v0", "one")
    snapshot("v2", "v0", "two")
    snapshot("v3", "v1", "one")
    data = module.history("branch")
    assert len(data["components"]) == 16
    versions = [row for row in data["versions"] if row["component_id"] == "instructions_rules"]
    assert len(versions) == 3
    assert versions[2]["parent_id"] == versions[0]["id"]
    assert data["decisions"] == []
    assert data["bundles"][-1]["components"] == data["bundles"][1]["components"]


def test_deleted_experiment_is_recoverable_and_cannot_start(tmp_path, profile):
    store = Store(tmp_path / 'state')
    store.create('removed', profile)
    evidence = tmp_path / 'answer.txt'
    evidence.write_text('recorded answer')
    assert store.transition('removed', 'delete') == {'id': 'removed', 'deleted': True}
    assert store.list() == []
    with pytest.raises(KeyError):
        store.get('removed')
    with pytest.raises(ValueError, match='Restore'):
        store.transition('removed', 'start')
    assert evidence.read_text() == 'recorded answer'
    assert Store(tmp_path / 'state').list() == []
    import sqlite3
    with pytest.raises(sqlite3.IntegrityError):
        store.create('removed', profile, settings={})
    store.transition('removed', 'restore')
    assert store.get('removed')['state'] == 'draft'
    assert [e['kind'] for e in store.events('removed')] == ['created', 'deleted', 'restored']


@pytest.mark.parametrize('state', ['queued', 'running', 'stopping'])
def test_deletion_rejects_active_experiments(tmp_path, profile, state):
    store = Store(tmp_path / 'state')
    store.create('active', profile)
    store.update('active', state=state)
    with pytest.raises(ValueError, match='Stop'):
        store.transition('active', 'delete')
    assert store.get('active')['state'] == state
    assert len(store.list()) == 1


def test_deleted_import_does_not_reappear_during_sync(tmp_path, profile, monkeypatch):
    from harnesslens.service import config
    monkeypatch.setattr(config, 'ROOT', tmp_path)
    directory = tmp_path / 'runs/local_experiments/imported'
    directory.mkdir(parents=True)
    (directory / 'configuration.json').write_text(json.dumps({'profile': str(profile)}))
    (directory / 'stage.json').write_text(json.dumps({'status': 'succeeded', 'stage': 'test_selected'}))
    (directory / 'result.json').write_text(json.dumps({'score': .75}))
    store = Store(tmp_path / 'state')
    store.sync_local_runs()
    assert store.get('imported')['read_only'] == 1
    store.transition('imported', 'delete')
    store.sync_local_runs()
    assert store.list() == []
    store.transition('imported', 'restore')
    assert store.get('imported')['read_only'] == 1
    assert json.loads((directory / 'result.json').read_text()) == {'score': .75}


def test_delete_api_requires_auth_and_supports_restore(tmp_path, profile):
    store = Store(tmp_path / 'state')
    store.create('api_delete', profile)
    token = 'test-token-' + 'x' * 24
    httpd = server(store, token, port=0, profiles=profile.parent)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    base = f'http://127.0.0.1:{httpd.server_port}'
    def post(action, authenticated=True):
        headers = {'Content-Type': 'application/json'}
        if authenticated:
            headers['Authorization'] = 'Bearer ' + token
        request = urllib.request.Request(base + '/v1/runs/api_delete/' + action, data=b'{}', headers=headers)
        return urllib.request.urlopen(request)
    try:
        with pytest.raises(urllib.error.HTTPError) as error:
            post('delete', authenticated=False)
        assert error.value.code == 401
        with post('delete') as response:
            assert json.load(response)['deleted'] is True
        assert not store.list()
        with post('restore') as response:
            assert json.load(response)['deleted'] is False
        assert store.get('api_delete')['state'] == 'draft'
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=2)
