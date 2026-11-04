"""Public deployment identifiers. Unconfigured identifiers grant no access."""
import json
import os
from pathlib import Path
from uuid import UUID


def _bindings():
    path = Path(os.environ.get('WORKRAG_BINDINGS_FILE', '/app/data/workrag-bindings.json'))
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding='utf-8'))


def _identifier(key):
    value = os.environ.get('WORKRAG_' + key.upper()) or _bindings().get(key)
    return str(UUID(value)) if value else ''


PIPELINE = _identifier('pipeline')
BOT = _identifier('bot')
KB = _identifier('kb')
NATIVE_AGENT = _identifier('native_agent')
