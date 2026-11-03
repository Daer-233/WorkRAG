"""Real retrieval -> container asset fetch -> Image components; no platform delivery."""
import json
import subprocess
import sys

import httpx

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location('connection', Path(__file__).with_name('connect-langbot-knowledge.py'))
connection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(connection)

with httpx.Client(base_url='http://127.0.0.1:5300', headers={'X-API-Key': connection.credential()}, timeout=120) as client:
    response = connection.data(client.post(f'/api/v1/knowledge/bases/{connection.KB}/retrieve',
                               json={'query': '请展示 AI 赋能设计培训现场照片'}))
    bot_config = connection.data(client.get('/api/v1/platform/bots/9777ca2e-7df1-4441-84ca-abedd4bc5c01'))['bot']['adapter_config'] if '--live-upload' in sys.argv else None
images = []
for item in response['results']:
    images.extend(item.get('metadata', {}).get('knowledge', {}).get('images', []))
assert images, 'No image evidence returned'
markdown = '来源：AI赋能设计培训回顾｜现场照片\n' + '\n'.join(
    f"![照片 {index + 1}]({item['thumbnail_url']})"
    for index, item in enumerate(images))
program = '''import asyncio, json, sys
from types import SimpleNamespace
from langbot.pkg.platform.adapters.dingtalk.adapter import DingTalkAdapter
from langbot.libs.dingtalk_api.api import DingTalkClient
import langbot_plugin.api.entities.builtin.platform.message as m
import httpx
async def main():
    adapter = object.__new__(DingTalkAdapter)
    payload = json.loads(sys.stdin.readline())
    markdown, config = payload['markdown'], payload['bot_config']
    real = DingTalkClient(config['client_id'], config['client_secret'], 'verification', '', True, None) if config else None
    class FakeBot:
        def __init__(self): self.sent = 0; self.text = ''
        async def get_legacy_access_token(self):
            return await real.get_legacy_access_token() if real else 'fixture'
        def _http_client_context(self):
            if real: return real._http_client_context()
            return httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'media_id':'@fixture'})))
        def _check_send_result(self, response): return response.json()
        async def send_card_message(self, *args):
            self.text = args[2]
            assert '127.0.0.1' not in args[2] and '![' in args[2]
        async def send_attachment(self, part, incoming):
            self.sent += 1
    bot = FakeBot()
    object.__setattr__(adapter, 'bot', bot)
    object.__setattr__(adapter, 'config', {})
    object.__setattr__(adapter, 'card_instance_id_dict', {'test':(None, 'test')})
    source = SimpleNamespace(source_platform_object=SimpleNamespace(incoming_message=SimpleNamespace()))
    message = SimpleNamespace(resp_message_id='test', tool_calls=None, content=markdown)
    await adapter.reply_message_chunk(source, message, m.MessageChain([m.Plain(text=markdown)]), is_final=True)
    assert bot.sent == 0 and bot.text.count('![') == payload['expected']
    assert '证据 ID' not in bot.text and '见随后发送' not in bot.text and '读取失败' not in bot.text
    print(json.dumps({'card_image_references':bot.text.count('!['),'separate_attachments':bot.sent,'source_preserved':'来源' in bot.text,'real_upload':bool(real),'platform_messages_sent':0}))
asyncio.run(main())
'''
subprocess.run(['docker', 'exec', '-i', 'langbot', '/app/.venv/bin/python', '-c', program],
               input=json.dumps({'markdown':markdown,'bot_config':bot_config,'expected':len(images)}) + '\n', text=True, check=True)
