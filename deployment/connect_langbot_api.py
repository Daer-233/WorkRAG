"""Import a user-supplied local API key and verify LangBot without logging it."""
import argparse
import json
from pathlib import Path
import re

import httpx
from dotenv import dotenv_values

ROOT=Path(__file__).resolve().parents[1]
PRIVATE=ROOT/'data/manuals/runtime/langbot-integration'

def read_key(path):
    text=path.read_text(encoding='utf-8-sig').strip()
    if not text: raise RuntimeError('API key file is empty')
    # Recognize the displayed MCP configuration, dotenv, header, or a bare key.
    try:
        value=json.loads(text)
        if isinstance(value,str): return value.strip()
        if isinstance(value,dict):
            server=value.get('mcpServers',{}).get('langbot',value)
            headers=server.get('headers',{})
            key=headers.get('X-API-Key') or value.get('LANGBOT_API_KEY') or value.get('api_key')
            if key: return str(key).strip()
    except json.JSONDecodeError: pass
    match=re.search(r'(?im)^\s*(?:LANGBOT_API_KEY|X-API-Key|API_KEY|APIKEY|API KEY|TOKEN|KEY|LANGBOT)\s*[:=]\s*[\"\x27]?([^\s\"\x27]+)',text)
    if match: return match.group(1)
    match=re.search(r'(?im)^\s*(?:Authorization:\s*)?Bearer\s+(\S+)',text)
    if match: return match.group(1)
    if len(text.splitlines())==1 and not any(c.isspace() for c in text): return text
    raise RuntimeError('API key file format not recognized; no contents printed')

def decoded(response):
    if response.status_code>=400:
        raise RuntimeError(f'LangBot returned HTTP {response.status_code}; response withheld')
    if 'text/event-stream' in response.headers.get('content-type',''):
        return next(json.loads(line[5:].strip()) for line in response.text.splitlines() if line.startswith('data:'))
    return response.json()

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--key-file',type=Path)
    args=parser.parse_args()
    key=read_key(args.key_file) if args.key_file else dotenv_values(PRIVATE/'.env').get('LANGBOT_API_KEY')
    if not key: raise RuntimeError('Missing private API credential')
    report={'base_url':'http://127.0.0.1:5300','mcp_url':'http://127.0.0.1:5300/mcp'}
    with httpx.Client(base_url=report['base_url'],headers={'X-API-Key':key},trust_env=False,timeout=30) as client:
        plugins_response=client.get('/api/v1/plugins')
        report['management_plugins_http_status']=plugins_response.status_code
        if plugins_response.status_code==200:
            plugins=decoded(plugins_response)
            report['installed_plugin_count']=len(plugins.get('data',{}).get('plugins',[]))
        headers={'Accept':'application/json, text/event-stream'}
        initialize=client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'workrag-local-setup','version':'1.0'}}})
        value=decoded(initialize)
        if 'error' in value: raise RuntimeError('MCP initialization rejected; response withheld')
        session=initialize.headers.get('mcp-session-id')
        if session: headers['Mcp-Session-Id']=session
        headers['MCP-Protocol-Version']=value['result']['protocolVersion']
        client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'})
        result=decoded(client.post('/mcp',headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}))
        if 'error' in result: raise RuntimeError('MCP tools listing rejected; response withheld')
        report['mcp_authenticated']=True
        report['mcp_tool_names']=[tool['name'] for tool in result['result'].get('tools',[])]
        if session: client.delete('/mcp',headers=headers)
    PRIVATE.mkdir(parents=True,exist_ok=True)
    (PRIVATE/'.env').write_text('LANGBOT_BASE_URL=http://127.0.0.1:5300\nLANGBOT_API_KEY='+key+'\n',encoding='utf-8')
    (PRIVATE/'api-connection.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__': main()
