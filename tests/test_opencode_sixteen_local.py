"""All component mechanisms, real pinned OpenCode and local synthetic responses.

No real model or company service is contacted. This checks loading/behavior,
not answer quality or optimization gains.
"""
import json
import os
from pathlib import Path
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.environ.get("HAI_RUN_OPENCODE_COMPONENT_PROBE") != "1", reason="opt in to real local 16-component probe")

MCP = '''import json, sys
for line in sys.stdin:
    request=json.loads(line)
    if 'id' not in request: continue
    method=request.get('method')
    result={}
    if method=='initialize': result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'component-probe','version':'1'}}
    elif method=='tools/list': result={'tools':[{'name':'ping','description':'MCP_DESCRIPTION_SENTINEL','inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}}]}
    elif method=='tools/call': result={'content':[{'type':'text','text':'MCP_EXECUTION_SENTINEL'}]}
    print(json.dumps({'jsonrpc':'2.0','id':request['id'],'result':result}),flush=True)
'''


def component_files():
    prompt = "SYSTEM_COMPONENT_SENTINEL AGENT_BODY_SENTINEL"
    config = {"agent": {"analyst": {"prompt": prompt}}, "default_agent": "analyst", "subagent_depth": 2,
        "tools": {"todowrite": False}, "permission": {"bash": {"*": "allow", "echo COMPONENT_DENIED": "deny"}},
        "references": {"handbook": {"path": "references/handbook", "description": "REFERENCE_DESCRIPTION_SENTINEL"}},
        "tool_output": {"max_bytes": 256, "max_lines": 10},
        "compaction": {"auto": True, "prune": True, "tail_turns": 2, "preserve_recent_tokens": 1000, "reserved": 8192},
        "experimental": {"continue_loop_on_deny": True, "primary_tools": ["probe"], "mcp_timeout": 5000},
        "mcp": {"probe": {"type": "local", "command": ["python", ".opencode/mcp/probe.py"], "enabled": True, "timeout": 5000}}}
    entries = {
        "AGENTS.md": "RESIDENT_COMPONENT_SENTINEL",
        "opencode.json": json.dumps(config),
        ".opencode/agents/analyst.md": f"---\ndescription: AGENT_DESCRIPTION_SENTINEL\nmode: primary\nsteps: 30\n---\n{prompt}",
        ".opencode/agents/helper.md": "---\ndescription: WORKER_DESCRIPTION_SENTINEL\nmode: subagent\nsteps: 2\n---\nSUBAGENT_SYSTEM_SENTINEL",
        ".opencode/skills/component-skill/SKILL.md": "---\nname: component-skill\ndescription: SKILL_COMPONENT_DESCRIPTION\n---\nSKILL_COMPONENT_BODY",
        ".opencode/commands/harnesslens_run.md": "---\ndescription: Component command\nagent: analyst\n---\nCOMMAND_COMPONENT_SENTINEL\n$ARGUMENTS",
        "references/handbook/info.md": "REFERENCE_BODY_SENTINEL",
        ".opencode/plugins/observe.js": "export default async () => ({'experimental.chat.system.transform': async (_, output) => {output.system.push('PLUGIN_EXECUTION_SENTINEL')}});",
        ".opencode/tools/probe.ts": "import {tool} from '@opencode-ai/plugin'; export default tool({description:'CUSTOM_TOOL_DESCRIPTION_SENTINEL', args:{query: tool.schema.string().describe('Probe query')}, async execute(){return 'CUSTOM_TOOL_EXECUTION_SENTINEL\\n'+'x'.repeat(4096)}})",
        ".opencode/mcp/probe.py": MCP,
    }
    return {"files": [{"scope": "project", "path": k, "content": v} for k, v in entries.items()]}


class Provider(BaseHTTPRequestHandler):
    calls = []
    completed = []
    def do_GET(self):
        raw = json.dumps(type(self).completed).encode()
        self.send_response(200); self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def do_POST(self):
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).calls.append(request)
        tool_messages = [m for m in request.get("messages", []) if m.get("role") == "tool"]
        sequence = [("skill", {"name": "component-skill"}), ("probe", {"query": "probe"}),
                    ("probe_ping", {"query": "probe"}), ("read", {"filePath": "references/handbook/info.md"}),
                    ("bash", {"command": "echo COMPONENT_DENIED", "description": "Exercise candidate deny rule"}),
                    ("task", {"description": "Run a small worker", "prompt": "Return CHILD_RESPONSE_SENTINEL", "subagent_type": "helper"})]
        delta = {"role": "assistant", "content": "Authority"}
        finish = "stop"
        if request.get("tools") and "SKILL_COMPONENT_DESCRIPTION" in json.dumps(request) and len(tool_messages) < len(sequence):
            tool, args = sequence[len(tool_messages)]
            delta = {"role": "assistant", "tool_calls": [{"index": 0, "id": "probe-call-" + str(len(tool_messages)),
                "type": "function", "function": {"name": tool, "arguments": json.dumps(args)}}]}
            finish = "tool_calls"
        if any("SUBAGENT_SYSTEM_SENTINEL" in str(m.get("content", "")) for m in request.get("messages", []) if m.get("role") == "system"):
            delta = {"role": "assistant", "content": "CHILD_RESPONSE_SENTINEL"}; finish = "stop"
        def chunk(value, reason=None, usage=None):
            event = {"id": "local-16-components", "object": "chat.completion.chunk", "model": request["model"],
                "created": 0, "choices": [{"index": 0, "delta": value, "finish_reason": reason}]}
            if usage: event["usage"] = usage
            return "data: " + json.dumps(event) + "\n\n"
        raw = (chunk(delta) + chunk({}, finish, {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}) + "data: [DONE]\n\n").encode()
        from harnesslens.infrastructure.chat_completions_proxy import _assemble_stream
        response, usage = _assemble_stream(raw.decode())
        type(self).completed.append({"request": request, "response": response, "usage": usage, "upstream_status": 200})
        self.send_response(200); self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw))); self.end_headers(); self.wfile.write(raw)
    def log_message(self, *_): pass


RECEIVER = '''import json, os, subprocess, urllib.request, uuid
from pathlib import Path
import harnesslens
from harnesslens.harnesses.opencode_execution import prepare_received_harness, refresh_report
from harnesslens.core.config import resolve_opencode_binary
from harnesslens.evaluation.native_benchmark import isolated_command
def solve(prompt, harness_files, tool_patches, component_policy, request_id, harness_digest, harness_version, model_url):
    root=Path(harnesslens.__file__).resolve().parents[1]
    workspace=root/'runs/receiver_checks'/uuid.uuid4().hex
    fixed={'model':'fdabench/glm-5.2','small_model':'fdabench/glm-5.2','provider':{'fdabench':{'npm':'@ai-sdk/openai-compatible','options':{'baseURL':model_url+'/v1','apiKey':'local-only'},'models':{'glm-5.2':{'name':'glm-5.2','limit':{'context':200000,'output':8192}}}}}}
    prepared=prepare_received_harness(workspace=workspace,harness_files=harness_files,tool_patches=tool_patches,component_policy=component_policy,fixed_config=fixed)
    env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TZ') if k in os.environ}
    env.update(prepared['environment'])
    port=__import__('urllib.parse',fromlist=['urlsplit']).urlsplit(model_url).port
    command=[str(resolve_opencode_binary()),*prepared['command_arguments'],prompt]
    with isolated_command(command,workspace,[port],()) as sandboxed:
        result=subprocess.run(sandboxed,cwd=workspace,env=env,capture_output=True,text=True,timeout=60)
    if result.returncode: raise RuntimeError(result.stderr)
    with urllib.request.urlopen(model_url+'/trace',timeout=5) as response: calls=json.load(response)
    trace=workspace/'api_calls.jsonl';trace.write_text(''.join(json.dumps(c)+'\\n' for c in calls))
    report=prepared['report']
    errors=refresh_report(report,workspace,trace)
    if errors: raise RuntimeError(str(errors))
    session_id=next(e['session_id'] for e in report['native_component_events'] if e.get('kind')=='command_invoked')
    receipt={'request_id':request_id,'harness_digest':harness_digest,'harness_version':harness_version,'opencode_version':'1.18.32','component_protocol':'harnesslens.opencode-components.v1','session_id':session_id}
    return {'answer':'Authority','messages':[{'role':'assistant','content':'Authority'}],'api_calls':calls,'usage':{'total_tokens':sum(c['usage']['total_tokens'] for c in calls)},'runtime_report':report,'harness_receipt':receipt}
'''


@pytest.mark.parametrize("transport", ["python", "http"])
def test_all_sixteen_through_business_receiver_and_real_native_execution(tmp_path, monkeypatch, transport):
    from harnesslens.harnesses.business_agent import load_config, invoke
    from harnesslens.harnesses.opencode_components import EDITABLE_IDS
    from harnesslens.harnesses.native_harness_driver import stable_hash
    from harnesslens.harnesses.channel_preflight import validate_channel_preflight
    import sys
    Provider.calls = []; Provider.completed = []
    model = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
    threading.Thread(target=model.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{model.server_address[1]}"
    monkeypatch.delenv("HAI_COMPONENT_POLICY", raising=False)
    module = tmp_path / "fixture_receiver.py"; module.write_text(RECEIVER)
    namespace = {}; exec(RECEIVER, namespace)
    server = None
    if transport == "http":
        class Service(BaseHTTPRequestHandler):
            def do_POST(self):
                try:
                    body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    result = namespace["solve"](**body)
                    self.send_response(200); self.end_headers(); self.wfile.write(json.dumps(result).encode())
                except Exception as exc:
                    self.send_response(500); self.end_headers(); self.wfile.write(str(exc).encode())
            def log_message(self, *_): pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Service)
        threading.Thread(target=server.serve_forever, daemon=True).start()
    path = tmp_path / "business.toml"
    connection = f'url="http://127.0.0.1:{server.server_address[1]}/solve"' if server else f'function="fixture_receiver:solve"\npython="{sys.executable}"\npython_paths=[".","{ROOT}"]\nsandbox="none"'
    mapping = "body" if server else "arguments"
    path.write_text(f'''[agent]
type="{transport}"
{connection}
timeout=90
api_calls_path="api_calls"
runtime_report_path="runtime_report"
require_harness_receipt=true
[agent.{mapping}]
prompt="{{prompt}}"
harness_files="{{harness_files}}"
tool_patches="{{tool_patches}}"
component_policy="{{component_policy}}"
request_id="{{request_id}}"
harness_digest="{{harness_digest}}"
harness_version="{{harness_version}}"
model_url="{url}"
[capabilities]
channels=["*"]
''')
    snapshot = component_files()
    files = {"home": {}, "project": {f["path"]: f["content"] for f in snapshot["files"]}}
    patches = {"bash": {"desc": "TOOL_DESCRIPTION_SENTINEL", "params": {"command": "TOOL_PARAMETER_SENTINEL"}}}
    context = {"prompt": "Answer the local probe", "harness_files": files, "tool_patches": patches,
               "request_id": uuid.uuid4().hex, "harness_digest": stable_hash(files), "harness_version": "sixteen-receiver"}
    from harnesslens.harnesses.component_policy import policy_contract
    context["component_policy"] = policy_contract()
    try:
        result = invoke(load_config(path), context, tmp_path / "transport")
        report = result["runtime_report"]
        trace = tmp_path / "api.jsonl"; trace.write_text(''.join(json.dumps(c) + '\n' for c in result["api_calls"]))
        row = {"agent_transport": transport, "model_request_evidence": True, "model_context": report, "api_calls_jsonl": str(trace)}
        trajectory = tmp_path / "trial.jsonl"; trajectory.write_text(json.dumps(row))
        preflight = validate_channel_preflight(decision={"candidate": {
            "channel_diffs": [{"channel_id": c} for c in sorted(EDITABLE_IDS)],
            "workspace_delta": {"files": [{**f, "change": "added"} for f in snapshot["files"]]},
            "manifest_delta": {"tool_desc_patches": patches}}},
            rollout={"per_task": {"probe": {"trajectory_paths": [str(trajectory)]}}}, output_path=tmp_path / "preflight.json")
        assert preflight["passed"]
        assert len(preflight["checks"]) == 16
        assert result["usage"]["total_tokens"] > 0
    finally:
        model.shutdown(); model.server_close()
        if server: server.shutdown(); server.server_close()
