import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

import httpx
import pytest

from harnesslens.core.model_config import configure_models, connection, proxy_environment, task_models
from harnesslens.harnesses.opencode_runtime import _start_proxy, _stop_process, validate_api_trace, write_opencode_config
from harnesslens.infrastructure.chat_completions_proxy import _assemble_stream
from harnesslens.service.config import invocation, load_profile
from harnesslens.service.store import Store


def test_start_requires_both_roles_before_queue_or_model_call(tmp_path):
    path = tmp_path / 'missing.toml'
    path.write_text('schema="harnesslens.experiment.v1"\n')
    store = Store(tmp_path / 'state')
    store.create('one', path)
    with pytest.raises(ValueError, match='models.execution and models.analysis'):
        store.transition('one', 'start')
    assert store.get('one')['state'] == 'draft'


def test_role_selection_overrides_legacy_shared_settings_and_does_not_fallback(tmp_path, model_tables, monkeypatch):
    path = tmp_path / 'profile.toml'
    path.write_text('schema="harnesslens.experiment.v1"\n' + model_tables)
    monkeypatch.setenv('DEEPSEEK_API_KEY', 'old-shared-secret')
    monkeypatch.setenv('HAI_CRM_MODEL', 'old/crm')
    monkeypatch.setenv('HAI_MODEL', 'old/analysis')
    _, env = invocation(load_profile(path), 'one')
    assert env['HAI_EXECUTION_MODEL'] == 'test/execution'
    assert env['HAI_ANALYSIS_MODEL'] == 'test/analysis'
    assert env['DEEPSEEK_API_KEY'] == 'execution-test-only'
    assert 'HAI_CRM_MODEL' not in env and 'HAI_MODEL' not in env
    receipt = json.loads(env['HAI_MODEL_CONNECTIONS'])
    assert 'test-only' not in json.dumps(receipt)
    env.pop('HAI_ANALYSIS_API_KEY')
    assert connection('analysis', env)['api_key'] == ''


def test_endpoint_change_blocks_resume_but_key_rotation_does_not(tmp_path, monkeypatch, model_tables):
    path = tmp_path / 'profile.toml'
    path.write_text('schema="harnesslens.experiment.v1"\n' + model_tables.replace('base_url="http://127.0.0.1:19001/v1"', 'base_url_env="TEST_EXECUTION_URL"'))
    monkeypatch.setenv('TEST_EXECUTION_URL', 'http://127.0.0.1:19001/v1')
    original = load_profile(path)['fingerprint']
    monkeypatch.setenv('TEST_EXECUTION_KEY', 'rotated-private-key')
    assert load_profile(path)['fingerprint'] == original
    store = Store(tmp_path / 'state'); store.create('one', path)
    monkeypatch.setenv('TEST_EXECUTION_URL', 'http://127.0.0.1:19003/v1')
    with pytest.raises(ValueError, match='changed'):
        store.transition('one', 'start')


def test_business_execution_is_owned_by_business_and_analysis_stays_local(tmp_path, model_tables):
    import tomllib
    models = tomllib.loads(model_tables)['models']
    models['execution'] = {'managed_by': 'business_agent'}
    env = {'TEST_ANALYSIS_KEY': 'analysis-only', 'HAI_EXECUTION_API_KEY': 'unwanted'}
    receipt = configure_models(models, env, business=True)
    assert receipt['execution'] == {'managed_by': 'business_agent'}
    assert 'HAI_EXECUTION_API_KEY' not in env
    assert 'DEEPSEEK_API_KEY' not in env
    assert env['HAI_ANALYSIS_API_KEY'] == 'analysis-only'
    with pytest.raises(ValueError, match='requires agent_config'):
        configure_models(models, env, business=False)


def test_direct_cli_requires_explicit_roles(monkeypatch):
    for name in list(__import__('os').environ):
        if name.startswith(('HAI_EXECUTION_', 'HAI_ANALYSIS_', 'HAI_MODEL_CONNECTIONS')):
            monkeypatch.delenv(name)
    with pytest.raises(ValueError, match='models.execution.model'):
        task_models()


def test_responses_config_uses_native_sdk_and_never_contains_provider_secret(tmp_path, monkeypatch):
    monkeypatch.setenv('HAI_ANALYSIS_API', 'responses')
    monkeypatch.setenv('HAI_ANALYSIS_API_KEY', 'secret-must-not-be-in-config')
    config = write_opencode_config(tmp_path, model='david/gpt-test', context_limit=200000,
        output_limit=1024, max_steps=3, model_options={'store': False}, base_url='http://127.0.0.1:123/v1')
    text = config.read_text()
    assert 'secret-must-not-be-in-config' not in text
    assert json.loads(text)['provider']['david']['npm'] == '@ai-sdk/openai'


def test_responses_stream_retains_native_reasoning_tools_and_usage():
    response = {'object': 'response', 'status': 'completed', 'output': [
        {'type': 'reasoning', 'encrypted_content': 'opaque-test'},
        {'type': 'function_call', 'call_id': 'call_1', 'name': 'lookup', 'arguments': '{"id":1}'}],
        'usage': {'input_tokens': 12, 'output_tokens': 3}}
    raw = 'event: response.completed\ndata: ' + json.dumps({'type': 'response.completed', 'response': response}) + '\n\n'
    actual, usage = _assemble_stream(raw)
    assert actual == response
    assert usage['total_tokens'] == 15


@pytest.mark.parametrize('failed', [False, True])
def test_proxy_routes_each_role_with_its_own_key_and_protocol(tmp_path, monkeypatch, failed):
    seen = []
    class Upstream(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            seen.append((self.path, self.headers.get('Authorization'), body))
            if self.path.endswith('/responses'):
                response = {'object': 'response', 'status': 'failed' if failed else 'completed',
                            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'OK'}]}],
                            'usage': {'input_tokens': 5, 'output_tokens': 2}}
                event = {'type': 'response.failed' if failed else 'response.completed', 'response': response}
                raw = ('data: ' + json.dumps(event) + '\n\n').encode()
                content_type = 'text/event-stream'
            else:
                raw = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'OK'}, 'finish_reason': 'stop'}],
                                  'usage': {'prompt_tokens': 5, 'completion_tokens': 2, 'total_tokens': 7}}).encode()
                content_type = 'application/json'
            self.send_response(200); self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(raw))); self.end_headers(); self.wfile.write(raw)
        def log_message(self, *_):
            pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        for role, api, path in [('execution', 'chat_completions', 'chat/completions'), ('analysis', 'responses', 'responses')]:
            prefix = 'HAI_' + role.upper()
            monkeypatch.setenv(prefix + '_API', api)
            monkeypatch.setenv(prefix + '_API_KEY', role + '-private')
            monkeypatch.setenv(prefix + '_BASE_URL', f'http://127.0.0.1:{server.server_port}/v1')
            proxy_env = proxy_environment(role)
            assert proxy_env['DEEPSEEK_API_KEY'] == role + '-private'
            assert 'HAI_ANALYSIS_API_KEY' not in proxy_env and 'HAI_EXECUTION_API_KEY' not in proxy_env
            assert 'TEST_EXECUTION_KEY' not in proxy_env and 'TEST_ANALYSIS_KEY' not in proxy_env
            root = tmp_path / role; root.mkdir()
            proxy, port = _start_proxy(run_root=root, call_id=role, role=role)
            try:
                payload = {'model': 'test', 'stream': api == 'responses',
                           'input' if api == 'responses' else 'messages': [{'role': 'user', 'content': 'hello'}]}
                result = httpx.post(f'http://127.0.0.1:{port}/v1/{path}', json=payload, timeout=10)
                assert result.status_code == 200
            finally:
                _stop_process(proxy)
            assert seen[-1][0] == '/v1/' + path
            assert seen[-1][1] == 'Bearer ' + role + '-private'
            if role == 'analysis':
                assert 'seed' not in seen[-1][2]
            trace = root / 'api_calls.jsonl'
            rows = [json.loads(x) for x in trace.read_text().splitlines()]
            assert rows[0]['usage']['total_tokens'] == 7
            assert (bool(validate_api_trace(trace))) == (failed and role == 'analysis')
            assert 'Bearer' not in trace.read_text() and '-private' not in trace.read_text()
    finally:
        server.shutdown(); server.server_close(); thread.join()


def test_direct_resume_refuses_model_change_and_ignores_key_rotation(tmp_path, monkeypatch, model_tables):
    import os
    monkeypatch.setattr(os, "environ", dict(os.environ))
    path = tmp_path / "models.toml"; path.write_text(model_tables)
    root = tmp_path / "run"
    first = task_models(path, run_root=root)
    monkeypatch.setenv("TEST_ANALYSIS_KEY", "rotated-private")
    assert task_models(path, run_root=root) == first
    path.write_text(model_tables.replace("test/analysis", "test/other-analysis"))
    with pytest.raises(ValueError, match="new run ID"):
        task_models(path, run_root=root)
    assert "private" not in (root / "model_connections.json").read_text()


def test_other_opencode_benchmarks_use_generic_execution_connection(tmp_path, monkeypatch):
    from harnesslens.core.model_config import apply_execution_provider
    monkeypatch.setenv("HAI_EXECUTION_MODEL", "chosen/gpt-execution")
    monkeypatch.setenv("HAI_EXECUTION_API", "responses")
    old = {"model": "old/model", "provider": {"old": {"models": {"model": {"limit": {"context": 100, "output": 20}}},
                "options": {"baseURL": "http://127.0.0.1:123/v1", "apiKey": "local-proxy"}}}}
    value = apply_execution_provider(old)
    assert value["model"] == "chosen/gpt-execution"
    assert value["provider"]["chosen"]["npm"] == "@ai-sdk/openai"
    assert value["provider"]["chosen"]["models"]["gpt-execution"]["limit"]["output"] == 20


def test_responses_behavioral_view_contains_question_tool_result_and_final_answer():
    from harnesslens.benchmarks.native_runtime import _messages
    from harnesslens.core.model_trace import tool_call_count
    request = {"instructions": "rules", "input": [
        {"role": "user", "content": [{"type": "input_text", "text": "question"}]},
        {"type": "function_call", "call_id": "c1", "name": "lookup", "arguments": "{}"},
        {"type": "function_call_output", "call_id": "c1", "output": "database result"}]}
    response = {"output": [{"type": "reasoning", "encrypted_content": "opaque"},
        {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "answer"}]}]}
    messages = _messages([{"request": request, "response": response}])
    assert [x["role"] for x in messages] == ["system", "user", "assistant", "tool", "assistant"]
    assert messages[2]["tool_calls"][0]["name"] == "lookup"
    assert messages[3]["content"] == "database result" and messages[4]["content"] == "answer"
    assert tool_call_count({"output": [request["input"][1]]}) == 1
