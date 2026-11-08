"""Normalize SDK content elements and standard MCP result envelopes."""
import json


def bounded_tool_json(value,budget=24000):
    """Reduce structured payloads without ever slicing a JSON document."""
    value=json.loads(json.dumps(value,ensure_ascii=False,default=str))
    def encode():return json.dumps(value,ensure_ascii=False)
    if len(encode())<=budget:return encode()
    value['truncated']=True
    if isinstance(value.get('history'),list):
        value['history']=value['history'][:5]
        for row in value['history']:
            row['question']=row.get('question','')[:800]
            row['answer']=row.get('answer','')[:1800]
    for key in ('history','results'):
        if isinstance(value.get(key),list):
            while len(encode())>budget and len(value[key])>1:value[key].pop()
    if len(encode())>budget and value.get('results'):
        row=value['results'][0];row['content']=row.get('content','')[:8000]
        meta=row.get('metadata',{})
        row['metadata']={k:meta[k] for k in ('entry_id','title','version','result_type') if k in meta}
    if len(encode())>budget:
        return json.dumps({'status':'tool_error','message':'工具结果超过上下文限制，请缩小查询范围。','results':[]},ensure_ascii=False)
    return encode()


def tool_result(value):
    if hasattr(value, 'model_dump'):
        value = value.model_dump(exclude_none=True)
    if isinstance(value, str):
        return tool_result(json.loads(value))
    if isinstance(value, dict):
        if value.get('isError'):
            return {'status': 'tool_error', 'results': []}
        if isinstance(value.get('structuredContent'), dict):
            return value['structuredContent']
        if 'status' in value:
            return value
        value = value.get('content', [])
    if isinstance(value, list):
        for element in value:
            if hasattr(element, 'model_dump'):
                element = element.model_dump(exclude_none=True)
            if isinstance(element, dict) and element.get('type') == 'text':
                try:
                    parsed = json.loads(element['text'])
                except (ValueError, KeyError):
                    continue
                if isinstance(parsed, dict) and 'status' in parsed:
                    return parsed
    raise ValueError('Tool returned no recognized result envelope')
