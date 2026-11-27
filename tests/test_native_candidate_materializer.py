"""Codex responses 代理的候选侧改写行为测试。

tau2/pi/codex 原生评测驱动已删除，仅保留代理层（仍在使用的通用机制）用例。
"""
from harnesslens.infrastructure.codex_responses_proxy import (
    _patch_tau2_tools,
    _translate_request,
)


def test_codex_proxy_patches_exact_tau2_tool_and_parameter_descriptions():
    tools = [
        {
            "type": "function",
            "function": {
                "name": "lookup_record",
                "description": "Original.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "record_id": {"type": "string", "description": "Original ID."}
                    },
                },
            },
        }
    ]

    patched = _patch_tau2_tools(
        tools,
        {
            "lookup_record": {
                "desc": "Patched Codex lookup description.",
                "params": {"record_id": "Patched Codex record identifier."},
            }
        },
    )

    function = patched[0]["function"]
    assert function["description"] == "Patched Codex lookup description."
    assert function["parameters"]["properties"]["record_id"]["description"] == (
        "Patched Codex record identifier."
    )


def test_codex_proxy_preserves_responses_instructions_for_upstream_model():
    translated = _translate_request(
        {
            "instructions": "Top-level developer and project context.",
            "input": [
                {
                    "role": "developer",
                    "content": [{"type": "input_text", "text": "Turn context."}],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Do the task."}],
                },
            ],
        }
    )

    assert translated["messages"] == [
        {"role": "system", "content": "Top-level developer and project context."},
        {"role": "system", "content": "Turn context."},
        {"role": "user", "content": "Do the task."},
    ]
