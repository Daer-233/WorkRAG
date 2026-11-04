"""Verify the actual manual_rag store with a disposable synthetic identity."""
import hashlib
import json
from pathlib import Path
import runpy
from uuid import uuid4


def main():
    runpy.run_path(str(Path(__file__).with_name('manual-instance.py')))['load']()
    from app.db.connection import connection
    from app.manuals.isolation import validate_isolation
    from app.manuals.session_memory import Begin, Finish, Reference, begin, finish, retrieval_scope

    validate_isolation()
    identity = (f'verify-{uuid4()}', 'bot', 'pipeline', 'chat', 'employee', 'initial')
    key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
    boot = uuid4()
    source = Reference(entry_id=uuid4(), title='Synthetic document', version='2025')

    def start(text):
        return begin(Begin(identity=identity, host_boot=boot, text=text))

    def complete(turn, sources):
        return finish(Finish(turn_id=turn['turn_id'], sources=sources))['saved']

    try:
        old = start('Older question')
        latest = start('New question')
        assert not complete(old, [source])
        assert complete(latest, [source])
        assert not complete(latest, [source])
        with connection() as conn:
            expiry = conn.execute('SELECT extract(epoch FROM expires_at-now()) AS seconds '
                                  'FROM manual_session_memory WHERE session_key=%s', (key,)).fetchone()
            assert 86390 <= expiry['seconds'] <= 86400
        followup = start('\u8fd8\u6709\u73b0\u573a\u7684\u56fe\u5417')
        assert followup['action'] == 'retrieve'
        assert retrieval_scope(followup['turn_id'])['source']['entry_id'] == str(source.entry_id)
        assert start('\u53d1\u6211\u539f\u6587\u4ef6')['stage'] == 'busy'
        assert complete(followup, [])
        assert retrieval_scope(followup['turn_id']) is None
        with connection() as conn:
            conn.execute("UPDATE manual_session_memory SET expires_at=now()-interval '1 second' WHERE session_key=%s", (key,))
        expired = start('\u8fd8\u6709\u73b0\u573a\u7684\u56fe\u5417')
        assert expired['action'] == 'reply' and '\u54ea\u4efd\u8d44\u6599' in expired['message']
    finally:
        with connection() as conn:
            conn.execute('DELETE FROM manual_session_memory WHERE session_key=%s', (key,))
    print('PostgreSQL retention, expiry, latest-turn protection and ticket invalidation passed.')


if __name__ == '__main__':
    main()
