"""Resolve signed work-library Markdown images for DingTalk card replies.

Only the fixed local library endpoint is fetched. Its signed capability is still
verified by the library; redirects, arbitrary hosts and arbitrary paths are denied.
No DingTalk messages are sent by this module.
"""
import base64
import re
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx

IMAGE = re.compile(r'!\[([^\]\n]*)\]\(([^\s)]+)\)')
ASSET = re.compile(r'/api/v1/manuals/assets/[0-9a-fA-F-]{36}\Z')
MAX_BYTES = 8 * 1024 * 1024
MAX_IMAGES = 12


def signed_asset(url):
    parts = urlsplit(url.replace('&amp;', '&'))
    relative = not parts.scheme and not parts.netloc and url.startswith('/api/v1/manuals/assets/')
    if not relative and (parts.scheme != 'http' or parts.netloc not in ('127.0.0.1:8060', 'localhost:8060')):
        return None
    if parts.fragment or not ASSET.fullmatch(parts.path):
        return None
    query = parse_qs(parts.query, keep_blank_values=True)
    if set(query) - {'access_token', 'variant'} or len(query.get('access_token', [])) != 1:
        return None
    if not query['access_token'][0] or query.get('variant', ['preview']) not in (['preview'], ['thumbnail']):
        return None
    return parts.path, query['access_token'][0]


def clean_text(text):
    # Evidence UUIDs remain in retrieval metadata; the human-facing source stays.
    text = re.sub(r'[（(]\s*证据\s*ID\s*[:：]\s*`?[0-9a-fA-F-]{36}`?\s*[）)]', '', text)
    text = re.sub(r'证据\s*ID\s*[:：]\s*`?[0-9a-fA-F-]{36}`?', '', text)
    return re.sub(r'\n[ \t]*\n(?:[ \t]*\n)+', '\n\n', text).strip()


async def upload_for_card(bot, encoded):
    """Upload only; never sends an independent chat message."""
    token = await bot.get_legacy_access_token()
    if not token:
        raise ValueError('Media authentication unavailable')
    async with bot._http_client_context() as client:
        response = await client.post('https://oapi.dingtalk.com/media/upload',
            params={'access_token': token, 'type': 'image'},
            files={'media': ('knowledge.png', base64.b64decode(encoded), 'image/png')}, timeout=30)
    uploaded = bot._check_send_result(response)
    media_id = uploaded.get('media_id')
    if not media_id or not re.fullmatch(r'@?[a-zA-Z0-9_-]+', media_id):
        raise ValueError('Invalid media ID')
    return media_id


async def render(text, client, upload_image=None):
    """Return card Markdown or legacy attachments, with order and visible failures."""
    attachments = []
    seen = {}
    replacements = []
    for match in IMAGE.finditer(text):
        reference = signed_asset(match[2])
        if reference is None:
            continue
        path, token = reference
        if path in seen:
            replacements.append((match, seen[path]))
            continue
        label = match[1] or '知识库配图'
        if len(seen) >= MAX_IMAGES:
            replacement = f'【{label}：本次图片数量已达上限，请继续请求其余照片】'
        else:
            try:
                # Thumbnails are generated locally, bounded, and sufficiently
                # small for mobile image delivery. Never expose local URLs.
                url = 'http://host.docker.internal:8060' + path + '?' + urlencode(
                    {'variant': 'thumbnail', 'access_token': token})
                async with client.stream('GET', url, headers={'Host': '127.0.0.1:8060'},
                                         follow_redirects=False, timeout=30) as response:
                    response.raise_for_status()
                    if not response.headers.get('content-type', '').startswith('image/'):
                        raise ValueError('Not an image')
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body.extend(chunk)
                        if len(body) > MAX_BYTES:
                            raise ValueError('Image too large')
                    if not body.startswith((b'\x89PNG\r\n\x1a\n', b'\xff\xd8\xff', b'RIFF')):
                        raise ValueError('Invalid image data')
                encoded = base64.b64encode(body).decode('ascii')
                if upload_image:
                    media_id = await upload_image(encoded)
                    replacement = f'![{label}]({media_id})'
                else:
                    attachments.append(encoded)
                    replacement = ''
            except (httpx.HTTPError, ValueError, RuntimeError):
                replacement = f'【{label}：图片读取失败，文字与来源仍可参考，请稍后重试】'
        seen[path] = replacement
        replacements.append((match, replacement))
    for match, replacement in reversed(replacements):
        text = text[:match.start()] + replacement + text[match.end():]
    return clean_text(text), attachments
