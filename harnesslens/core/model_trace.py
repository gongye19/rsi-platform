"""Common behavioral view of native API traces; raw API records stay intact."""


def conversation(request, response):
    response = response or {}
    if 'input' not in request:
        messages = list(request.get('messages', []))
        choices = response.get('choices', [])
        if choices and choices[0].get('message'):
            messages.append(choices[0]['message'])
        return messages
    messages = []
    if request.get('instructions'):
        messages.append({'role': 'system', 'content': request['instructions']})
    items = request.get('input', [])
    if isinstance(items, str):
        items = [{'role': 'user', 'content': items}]
    for item in [*items, *response.get('output', [])]:
        kind = item.get('type')
        if kind == 'function_call':
            messages.append({'role': 'assistant', 'content': None, 'tool_calls': [
                {'id': item.get('call_id'), 'function': {'name': item.get('name'), 'arguments': item.get('arguments')}}]})
        elif kind == 'function_call_output':
            messages.append({'role': 'tool', 'tool_call_id': item.get('call_id'), 'content': item.get('output')})
        elif item.get('role'):
            content = item.get('content', '')
            if isinstance(content, list):
                # Text-only conversations remain convenient for the analyzer;
                # preserve structured attachments when any non-text item exists.
                if all(part.get('type') in {'input_text', 'output_text', 'text'} for part in content):
                    content = '\n'.join(part.get('text', '') for part in content)
            messages.append({'role': item['role'], 'content': content})
    return messages


def tool_call_count(response):
    response = response or {}
    return (sum(len(choice.get('message', {}).get('tool_calls', [])) for choice in response.get('choices', []))
            + sum(item.get('type') == 'function_call' for item in response.get('output', [])))
