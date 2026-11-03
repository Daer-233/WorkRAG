import asyncio
import base64

import httpx

from knowledge_dingtalk_media import render, signed_asset, clean_text, upload_for_card

URL = 'http://127.0.0.1:8060/api/v1/manuals/assets/1fd0f00d-962d-46a4-b8ff-75701e1db875?access_token=test'
PNG = b'\x89PNG\r\n\x1a\nfixture'


def test_allowlist():
    assert signed_asset(URL)
    assert signed_asset(URL.removeprefix('http://127.0.0.1:8060'))
    assert signed_asset('//evil.example' + URL.removeprefix('http://127.0.0.1:8060')) is None
    for url in (URL.replace('127.0.0.1', 'evil.example'), URL.replace('/assets/', '/other/'),
                URL + '&access_token=second', URL + '&redirect=http://evil',
                URL.replace('http:', 'https:'), URL + '#fragment'):
        assert signed_asset(url) is None


def test_order_dedup_and_failed_image():
    async def run():
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(200, headers={'content-type': 'image/png'}, content=PNG)
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            relative = URL.removeprefix('http://127.0.0.1:8060')
            text, images = await render(f'来源 A\n![老师]({relative})\n![重复]({URL})', client)
        assert len(requests) == len(images) == 1
        assert base64.b64decode(images[0]) == PNG
        assert '来源 A' in text and '配图' not in text and '127.0.0.1' not in text
        assert requests[0].url.host == 'host.docker.internal'
        assert requests[0].headers['host'] == '127.0.0.1:8060'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(403))) as client:
            text, images = await render(f'来源 B ![老师]({URL})', client)
        assert not images and '读取失败' in text and '来源 B' in text
    asyncio.run(run())


def test_card_media_and_clean_sources():
    async def run():
        uploads = []
        async def upload(encoded):
            uploads.append(encoded)
            return '@media_fixture'
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200,
                headers={'content-type':'image/png'}, content=PNG))) as client:
            text, images = await render(f'老师（证据 ID：`1fd0f00d-962d-46a4-b8ff-75701e1db875`）\n![老师]({URL})\n来源：《培训回顾》', client, upload_image=upload)
        assert not images and len(uploads) == 1
        assert '![老师](@media_fixture)' in text
        assert '证据' not in text and '配图 1' not in text and '来源：《培训回顾》' in text
        assert '127.0.0.1' not in text
    asyncio.run(run())


def test_redirect_is_not_followed():
    async def run():
        requests = []
        def handler(request):
            requests.append(request)
            return httpx.Response(302, headers={'location': 'http://evil.example'})
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            text, images = await render(f'![照片]({URL})', client)
        assert len(requests) == 1 and not images and '读取失败' in text
    asyncio.run(run())
