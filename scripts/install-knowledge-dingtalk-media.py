"""Install the small local DingTalk adapter extension; rerun after image upgrades."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / 'data/manuals/runtime'
TARGET = '/app/src/langbot/pkg/platform/adapters/dingtalk'


def main():
    RUNTIME.mkdir(parents=True, exist_ok=True)
    current = RUNTIME / 'dingtalk-adapter.current.py'
    subprocess.run(['docker', 'cp', f'langbot:{TARGET}/adapter.py', str(current)], check=True)
    source = current.read_text(encoding='utf-8')
    marker = '    async def _work_knowledge_media('
    if marker in source:
        start = source.index(marker)
        end = source.index('    async def reply_message(\n', start)
        source = source[:start] + source[end:]
        source = source.replace('        if is_final and bot_message.tool_calls is None:\n            message = await self._work_knowledge_media(message)\n', '')
        source = source.replace('        message = await self._work_knowledge_media(message)\n', '')
    if marker not in source:
        backup = RUNTIME / 'dingtalk-adapter.before-media.py'
        if not backup.exists():
            backup.write_text(source, encoding='utf-8')
        method = '''    async def _work_knowledge_media(self, message):
        from .knowledge_media import render, signed_asset
        import httpx

        from .knowledge_media import upload_for_card
        async def upload_image(encoded):
            return await upload_for_card(self.bot, encoded)
        converted = []
        async with httpx.AsyncClient() as client:
            for part in message:
                if isinstance(part, platform_message.Plain):
                    text, images = await render(part.text, client, upload_image=upload_image)
                    converted.append(platform_message.Plain(text=text))
                    converted.extend(platform_message.Image(base64=data) for data in images)
                elif isinstance(part, platform_message.Image) and part.url and signed_asset(part.url):
                    text, images = await render(f'![知识库配图]({part.url})', client, upload_image=upload_image)
                    converted.append(platform_message.Plain(text=text))
                    converted.extend(platform_message.Image(base64=data) for data in images)
                else:
                    converted.append(part)
        return platform_message.MessageChain(converted)

'''
        anchor = '    async def reply_message(\n'
        assert source.count(anchor) == 1, 'Adapter structure changed; refusing to patch'
        source = source.replace(anchor, method + anchor)
        anchor = '        incoming_message = message_source.source_platform_object.incoming_message\n'
        # Only the reply_message occurrence, not other adapter methods.
        start = source.index('    async def reply_message(\n')
        pos = source.index(anchor, start) + len(anchor)
        source = source[:pos] + '        message = await self._work_knowledge_media(message)\n' + source[pos:]
        anchor = '        message_id = bot_message.resp_message_id\n'
        assert source.count(anchor) == 1, 'Streaming adapter structure changed'
        source = source.replace(anchor, '''        if is_final and bot_message.tool_calls is None:
            message = await self._work_knowledge_media(message)
''' + anchor)
        compile(source, 'adapter.py', 'exec')
        current.write_text(source, encoding='utf-8')
    subprocess.run(['docker', 'cp', str(ROOT / 'scripts/knowledge_dingtalk_media.py'),
                    f'langbot:{TARGET}/knowledge_media.py'], check=True)
    subprocess.run(['docker', 'cp', str(current), f'langbot:{TARGET}/adapter.py'], check=True)
    subprocess.run(['docker', 'exec', 'langbot', '/app/.venv/bin/python', '-c',
                    'from langbot.pkg.platform.adapters.dingtalk.adapter import DingTalkAdapter; '
                    'assert hasattr(DingTalkAdapter, "_work_knowledge_media"); print("media adapter import OK")'], check=True)
    print('Installed. Restart langbot to activate. No messages sent.')


if __name__ == '__main__':
    main()
