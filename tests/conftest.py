import json
from pathlib import Path
import sys
import uuid

import pytest


@pytest.fixture
def business_benchmark(tmp_path, monkeypatch):
    """最小 business_extension benchmark 描述符：供需要 adapter 的服务级测试使用。"""
    from harnesslens.benchmarks.cell_config import benchmark_config

    monkeypatch.setenv("HAI_BENCHMARK_CONFIG", "")
    monkeypatch.delenv("HAI_AGENT_CONFIG", raising=False)
    name = "svc_" + uuid.uuid4().hex[:12]
    ids = [f"task-{index}" for index in range(30)]
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(
        "".join(
            json.dumps({"id": tid, "question": f"q {tid}", "answer": tid}) + "\n"
            for tid in [*ids, "task-holdout"]
        )
    )
    spec = tmp_path / "benchmark.toml"
    spec.write_text(
        f'schema="harnesslens.business-benchmark.v1"\nid="{name}"\ntasks="tasks.jsonl"\n'
        f'train={json.dumps(ids)}\ntest=["task-holdout"]\npublic_fields=["question"]\n'
    )
    agent = tmp_path / "agent.toml"
    agent.write_text(
        '[agent]\ntype="python"\nname="local-probe"\nfunction="agent:solve"\n'
        f'python="{sys.executable}"\npython_paths=[]\ntimeout=10\n'
        '[agent.arguments]\nquestion="{prompt}"\n[capabilities]\nchannels=["instructions_rules"]\n'
    )
    monkeypatch.setenv("HAI_AGENT_CONFIG", str(agent))
    cell = benchmark_config(tmp_path, str(spec)).cell
    # runtime_sources() 中的绝对路径指向真实仓库文件，直接参与哈希；
    # 相对路径（common 文件）需在临时 repo 落盘才能被指纹读到。
    for relative in benchmark_config(tmp_path, str(spec)).runtime_files():
        if Path(relative).is_absolute():
            continue
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(relative, encoding="utf-8")
    return tmp_path, cell


@pytest.fixture
def model_tables(monkeypatch):
    monkeypatch.setenv('TEST_EXECUTION_KEY', 'execution-test-only')
    monkeypatch.setenv('TEST_ANALYSIS_KEY', 'analysis-test-only')
    return '''
[models.execution]
model="test/execution"
api="chat_completions"
base_url="http://127.0.0.1:19001/v1"
api_key_env="TEST_EXECUTION_KEY"
[models.analysis]
model="test/analysis"
api="responses"
base_url="http://127.0.0.1:19002/v1"
api_key_env="TEST_ANALYSIS_KEY"
'''
