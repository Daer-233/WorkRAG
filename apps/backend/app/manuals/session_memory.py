"""Persist only cited references and the current conversation decision."""
import hashlib
import hmac
import json
import re
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import Response
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.db.connection import connection
from .isolation import DATA, inside_data
from .store import ManualStore

TOKEN_FILE = DATA / 'runtime' / 'session-memory-token.private'
SCHEMA = Path(__file__).with_suffix('.sql')
Kind = Literal['images', 'source_file', 'next_step', 'context']
IdentityPart = Annotated[str, StringConstraints(min_length=1, max_length=256)]
NEED_SOURCE = '请说一下你指的是哪份资料，或重新提出原来的问题。'
MAX_FILE_BYTES = 10 * 1024 * 1024


class Payload(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Reference(Payload):
    entry_id: UUID
    title: str = Field(min_length=1, max_length=300)
    version: str = Field(max_length=120)
    cursor: UUID | None = None


class Begin(Payload):
    identity: tuple[IdentityPart, IdentityPart, IdentityPart, IdentityPart, IdentityPart, IdentityPart]
    host_boot: UUID
    text: str = Field(max_length=4000)
    has_attachment: bool = False


class Finish(Payload):
    turn_id: UUID
    sources: list[Reference] = Field(max_length=12)
    offered_file: bool = False


class FileRequest(Payload):
    turn_id: UUID


def normalize(text):
    return re.sub(r'[\s，。？！、,.!?]+', '', text.strip()).casefold()


def intent(text, offered_file):
    if re.fullmatch(r'(?:那|然后)?下(?:一|个)步(?:呢|怎么做|是什么)?', text):
        return 'next_step'
    if re.fullmatch(r'(?:还有|有|有没有|给我看|我想看|发我|看看|看一下|看看刚才的)(?:刚才(?:那份)?的?|这份的?|现场的?)?(?:图|图片|照片|截图|配图)(?:吗|呢|能给我看看吗)?', text):
        return 'images'
    if (re.fullmatch(r'(?:请|麻烦)?(?:把)?(?:刚才(?:那份)?的?|上一份的?|这份的?)?(?:发我|发给我|给我|需要|我要)(?:刚才(?:那份)?的?|这份的?)?(?:源文件|原文件|原件|整理稿)', text)
            or re.fullmatch(r'(?:把)?(?:刚才那份|上一份|这份)(?:资料)?的?(?:原文件|源文件|原件)(?:发我|发给我|给我)?', text)
            or (offered_file and text in {'需要', '要', '发给我', '发我'})):
        return 'source_file'
    if text in {'刚才那份', '刚才那份呢', '这份呢', '上一份呢', '继续讲刚才那份'}:
        return 'context'
    return None


def choice(text, sources):
    number = re.fullmatch(r'(?:第)?([0-9]{1,2}|[一二三四五六七八九十]|十一|十二)(?:份|项|个)?', text)
    if number:
        value = number[1]
        index = int(value) if value.isascii() else '一 二 三 四 五 六 七 八 九 十 十一 十二'.split().index(value) + 1
        return True, sources[index - 1] if 1 <= index <= len(sources) else None
    matches = [source for source in sources if text in {
        normalize(source['title']), normalize(label(source)),
    }]
    return bool(matches), matches[0] if len(matches) == 1 else None


def label(source):
    return f'{source["title"]}（{source["version"] or "版本未标注"}）'


def begin(payload: Begin):
    key = hashlib.sha256(json.dumps(payload.identity, ensure_ascii=False).encode()).hexdigest()
    with connection() as conn:
        row = conn.execute('''INSERT INTO manual_session_memory (session_key) VALUES (%s)
                              ON CONFLICT (session_key) DO UPDATE SET session_key=EXCLUDED.session_key
                              RETURNING *, expires_at > now() AS live, turn_expires_at > now() AS running''', (key,)).fetchone()
        sources = row['sources'] if row['live'] else []
        text = normalize(payload.text)
        kind = intent(text, row['live'] and row['offered_file']) if not payload.has_attachment else None
        selected, source = False, None
        if row['live'] and row['pending'] and not payload.has_attachment:
            selected, source = choice(text, sources)
            if selected:
                kind = row['pending']
        if kind and row['running'] and row['host_boot'] == payload.host_boot:
            return {'action': 'reply', 'stage': 'busy', 'message': '上一条消息还在处理，请等它完成后再追问。'}
        if kind and not sources:
            return {'action': 'reply', 'message': NEED_SOURCE}
        if kind and source is None and (selected or len(sources) > 1):
            conn.execute('''UPDATE manual_session_memory SET pending=%s, expires_at=now()+interval '24 hours',
                            turn_id=NULL, retrieval=NULL, turn_expires_at=NULL WHERE session_key=%s''', (kind, key))
            lines = [f'{index}. {label(item)}' for index, item in enumerate(sources, 1)]
            return {'action': 'reply', 'message': '你指的是哪一份资料？请回复序号或资料名。\n' + '\n'.join(lines)}

        turn_id = uuid4()
        scope = {'kind': kind, 'source': source or sources[0]} if kind else None
        conn.execute('''UPDATE manual_session_memory SET turn_id=%s, host_boot=%s,
                          turn_expires_at=now()+interval '10 minutes', retrieval=%s,
                          pending=NULL, sources=%s, offered_file=%s, file_claimed=false WHERE session_key=%s''',
                     (turn_id, payload.host_boot, Jsonb(scope) if scope else None,
                      Jsonb(sources if scope else []), bool(scope and row['offered_file']), key))
        return {'action': 'retrieve' if scope else 'ordinary', 'turn_id': str(turn_id),
                'has_references': bool(sources), **(scope or {})}


def finish(payload: Finish):
    with connection() as conn:
        if payload.sources:
            result = conn.execute('''UPDATE manual_session_memory SET sources=%s, offered_file=%s,
                expires_at=now()+interval '24 hours', turn_id=NULL, turn_expires_at=NULL, retrieval=NULL
                WHERE turn_id=%s AND turn_expires_at>now()''',
                (Jsonb([source.model_dump(mode='json') for source in payload.sources]),
                 payload.offered_file, payload.turn_id))
        else:
            # A failed scoped attempt leaves the existing reference and expiration intact.
            result = conn.execute('''UPDATE manual_session_memory SET turn_id=NULL, turn_expires_at=NULL, retrieval=NULL
                WHERE turn_id=%s AND turn_expires_at>now()''', (payload.turn_id,))
        return {'saved': result.rowcount == 1}


def retrieval_scope(turn_id):
    with connection() as conn:
        row = conn.execute('''SELECT retrieval FROM manual_session_memory WHERE turn_id=%s
                              AND turn_expires_at>now() AND expires_at>now()''', (turn_id,)).fetchone()
    return row['retrieval'] if row else None


def file_for_turn(payload: FileRequest):
    from .session_followup import published

    with connection() as conn:
        claimed = conn.execute('''UPDATE manual_session_memory SET file_claimed=true
            WHERE turn_id=%s AND turn_expires_at>now() AND expires_at>now()
            AND retrieval->>'kind'='source_file' AND NOT file_claimed RETURNING retrieval''',
            (payload.turn_id,)).fetchone()
        if not claimed:
            raise HTTPException(status_code=409, detail='本轮附件发送资格已失效')
        reference = claimed['retrieval']['source']
        try:
            entry = ManualStore().get(UUID(reference['entry_id']))
            if not published(entry, reference['version']) or not entry.get('source_path'):
                raise ValueError('Source is unavailable')
            path = inside_data(entry['source_path'])
            with path.open('rb') as original:
                content = original.read(MAX_FILE_BYTES + 1)
        except (ValueError, OSError):
            raise HTTPException(status_code=404, detail='资料版本或源文件当前不可用') from None
        if not content or len(content) > MAX_FILE_BYTES:
            raise HTTPException(status_code=413, detail='文件为空或超过钉钉发送上限')
        name = (entry.get('source_name') or path.name).replace('\\', '/').rsplit('/', 1)[-1]
        name = re.sub(r'[\x00-\x1f\x7f]', '', name).strip()
        if not name or not Path(name).suffix:
            raise HTTPException(status_code=415, detail='文件名没有可识别的扩展名')
        if path.suffix.lower() == '.md':
            name = str(Path(name).with_suffix('.txt'))
    return Response(content, media_type='application/octet-stream',
                    headers={'X-Session-Filename': quote(name, safe=''), 'Cache-Control': 'no-store'})


def cleanup():
    with connection() as conn:
        conn.execute('''DELETE FROM manual_session_memory WHERE expires_at<=now()
                        AND (turn_expires_at IS NULL OR turn_expires_at<=now())''')


def authenticate(x_session_memory_token: Annotated[str | None, Header()] = None):
    try:
        expected = TOKEN_FILE.read_text(encoding='ascii').strip()
    except OSError:
        expected = ''
    if len(expected) < 32 or not hmac.compare_digest(expected.encode(), (x_session_memory_token or '').encode()):
        raise HTTPException(status_code=403, detail='需要会话记忆服务凭据')


router = APIRouter(prefix='/api/v1/manuals/internal/session-memory', dependencies=[Depends(authenticate)])
router.add_api_route('/begin', begin, methods=['POST'])
router.add_api_route('/finish', finish, methods=['POST'])
router.add_api_route('/file', file_for_turn, methods=['POST'])
