"""Request visibility compares decoded text and preserves its message role."""
import json

import pytest

from harnesslens.harnesses.component_preflight import check_components


@pytest.mark.parametrize('make_request',[
    lambda text:{'messages':[{'role':'system','content':text}]},
    lambda text:{'messages':[{'role':'developer','content':[{'type':'text','text':text}]}]},
    lambda text:{'instructions':text,'input':[{'role':'user','content':'Task'}]},
    lambda text:{'input':[{'role':'developer','content':[{'type':'input_text','text':text}]}]},
])
def test_native_prompt_visibility_preserves_multiline_quoted_unicode_text(tmp_path,make_request):
    prompt='First line: "verify".\n\n路径 C:\\data; keep literal \\n unchanged.'
    candidate={'workspace_delta':{'files':[{'scope':'project','path':'opencode.json','content':json.dumps({'agent':{'build':{'prompt':prompt}}})}]}}
    trace=tmp_path/'api_calls.jsonl'
    trace.write_text(json.dumps({'request':make_request(prompt)})+'\n')
    context={'native_component_events':[{'kind':'config_loaded'}],'effective_config':{'agent':{'build':{'prompt':prompt}}}}
    checks=check_components({'system_prompt'},candidate,context,{'api_calls_jsonl':str(trace)})
    assert checks[0]['passed'],checks


@pytest.mark.parametrize('entry',[
    {'request':{'messages':[{'role':'user','content':'Expected\nprompt'}]}},
    {'role':'user_sim','request':{'messages':[{'role':'system','content':'Expected\nprompt'}]}},
    {'request':{'messages':[{'role':'system','content':'Different prompt'}]}},
])
def test_prompt_in_user_text_simulator_or_unrelated_system_message_does_not_pass(tmp_path,entry):
    prompt='Expected\nprompt'
    candidate={'manifest_delta':{'config_patch':{'agent.build.prompt':prompt}}}
    trace=tmp_path/'api_calls.jsonl';trace.write_text(json.dumps(entry)+'\n')
    context={'native_component_events':[{'kind':'config_loaded'}],'effective_config':{'agent':{'build':{'prompt':prompt}}}}
    checks=check_components({'system_prompt'},candidate,context,{'api_calls_jsonl':str(trace)})
    assert not checks[0]['passed']


def test_multiline_resident_rules_and_skill_catalog_are_checked_as_decoded_text(tmp_path):
    rule='Check "source".\nThen verify the answer.'
    description='Find "records" at C:\\data'
    files=[{'scope':'project','path':'AGENTS.md','content':rule},
           {'scope':'project','path':'.opencode/skills/lookup/SKILL.md','content':f'---\nname: lookup\ndescription: {description}\n---\nSkill body'}]
    trace=tmp_path/'api_calls.jsonl';trace.write_text(json.dumps({'request':{'messages':[{'role':'system','content':rule+'\n'+description}]}})+'\n')
    checks=check_components({'instructions_rules','skills'},{'workspace_delta':{'files':files}},
        {'native_component_events':[{'kind':'config_loaded'}],'candidate_files':files},{'api_calls_jsonl':str(trace)})
    assert all(check['passed'] for check in checks),checks
