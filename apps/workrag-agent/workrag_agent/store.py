import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import jieba
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from rank_bm25 import BM25Okapi

from .security import identity_key,actor_key


def normalize(text):
    return re.sub(r'[\s，。？！、,.!?：:]+','',text).casefold()


class Store:
    def __init__(self,dsn): self.dsn=dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self.dsn,row_factory=dict_row) as conn: yield conn

    def setup(self):
        with self.connection() as c:
            c.execute(Path(__file__).with_name('schema.sql').read_text(encoding='utf-8'))
            if c.execute("SELECT to_regclass('public.checkpoints') AS name").fetchone()['name']:
                for table in ('checkpoints','checkpoint_writes','checkpoint_blobs'):
                    c.execute(f'ALTER TABLE {table} ADD COLUMN IF NOT EXISTS wa_created_at TIMESTAMPTZ NOT NULL DEFAULT now()')
                c.execute('CREATE INDEX IF NOT EXISTS wa_checkpoint_retention ON checkpoints(wa_created_at)')

    def session(self,identity):
        key=identity_key(identity)
        with self.connection() as c:
            row=c.execute('''INSERT INTO wa_sessions(session_key,identity) VALUES(%s,%s)
                ON CONFLICT(session_key) DO UPDATE SET updated_at=now() RETURNING *''',(key,Jsonb(identity))).fetchone()
        return row

    def previous(self,key,event_id):
        with self.connection() as c:
            return c.execute('SELECT * FROM wa_answers WHERE session_key=%s AND event_id=%s',(key,event_id)).fetchone()

    def clear_pending(self,key):
        with self.connection() as c:c.execute('UPDATE wa_sessions SET pending=NULL WHERE session_key=%s',(key,))

    def recent(self,key):
        with self.connection() as c:
            rows=c.execute('SELECT question,answer FROM wa_answers WHERE session_key=%s AND created_at>now()-interval \'90 days\' ORDER BY created_at DESC LIMIT 3',(key,)).fetchall()
        return list(reversed(rows))

    def search_history(self,identity,query,limit=10):
        with self.connection() as c:
            rows=c.execute('''SELECT a.id,a.question,a.answer,a.created_at FROM wa_answers a
              JOIN wa_sessions s ON s.session_key=a.session_key WHERE a.workspace=%s
              AND a.actor_key=%s AND s.identity->>'bot'=%s AND a.created_at>now()-interval '90 days'
              AND (a.question ILIKE %s OR a.answer ILIKE %s) ORDER BY a.created_at DESC LIMIT %s''',
              (identity['workspace'],actor_key(identity),identity['bot'],'%'+query.replace('%','\\%').replace('_','\\_')+'%',
               '%'+query.replace('%','\\%').replace('_','\\_')+'%',min(max(limit,1),10))).fetchall()
        return json.loads(json.dumps(rows,default=str))

    def finish(self,identity,event_id,question,answer,refs,pending=None,card_id=None,simulation=False):
        key=identity_key(identity)
        with self.connection() as c:
            row=c.execute('''INSERT INTO wa_answers(id,workspace,actor_key,session_key,event_id,question,answer,refs,card_id,simulation)
             VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(session_key,event_id) DO UPDATE SET event_id=EXCLUDED.event_id RETURNING *''',
             (uuid4(),identity['workspace'],actor_key(identity),key,event_id,question,answer,Jsonb(refs),card_id,simulation)).fetchone()
            c.execute('UPDATE wa_sessions SET refs=%s,pending=%s,updated_at=now() WHERE session_key=%s',
                      (Jsonb(refs),Jsonb(pending) if pending else None,key))
        return str(row['id'])

    def feedback(self,identity,event_id,answer_id,vote,reason='',revision=1):
        if vote not in ('positive','negative','unknown'): raise ValueError('Invalid vote')
        workspace=identity['workspace']; actor=actor_key(identity)
        with self.connection() as c:
            row=c.execute('''SELECT * FROM wa_answers WHERE id=%s AND workspace=%s AND actor_key=%s
              AND session_key IN (SELECT session_key FROM wa_sessions WHERE identity->>'bot'=%s) FOR UPDATE''',
                          (answer_id,workspace,actor,identity['bot'])).fetchone()
            if not row or row['revision']!=revision: raise PermissionError('Answer is unavailable to this actor or revision')
            inserted=c.execute('''INSERT INTO wa_feedback_events(workspace,event_id,answer_id,actor_key,vote,reason)
              VALUES(%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING RETURNING event_id''',
              (workspace,event_id,answer_id,actor,vote,reason[:2000])).fetchone()
            if not inserted: return {'duplicate':True}
            c.execute('''INSERT INTO wa_feedback(answer_id,actor_key,vote,reason) VALUES(%s,%s,%s,%s)
              ON CONFLICT(answer_id,actor_key) DO UPDATE SET vote=EXCLUDED.vote,reason=EXCLUDED.reason,updated_at=now()''',
              (answer_id,actor,vote,reason[:2000]))
            if vote=='positive':
                c.execute('''INSERT INTO wa_candidates(id,workspace,answer_id,question,answer,refs,simulation)
                  VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(answer_id) DO NOTHING''',
                  (uuid4(),workspace,answer_id,row['question'],row['answer'],Jsonb(row['refs']),row['simulation']))
            elif vote=='negative':
                c.execute("UPDATE wa_candidates SET review_reason=%s,updated_at=now() WHERE answer_id=%s",(reason or '收到负反馈，请复查',answer_id))
        return {'saved':True,'vote':vote}

    def candidates(self,workspace):
        with self.connection() as c:
            rows=c.execute('''SELECT c.*,a.question AS original_question,a.answer AS original_answer,
              (SELECT jsonb_agg(jsonb_build_object('vote',f.vote,'reason',f.reason)) FROM wa_feedback f WHERE f.answer_id=c.answer_id) AS feedback,
              (SELECT jsonb_agg(to_jsonb(h)) FROM (SELECT h.question,h.answer,h.created_at FROM wa_answers h
                 WHERE h.session_key=a.session_key AND h.created_at<=a.created_at AND h.created_at>now()-interval '90 days'
                 ORDER BY h.created_at DESC LIMIT 4) h) AS context
              FROM wa_candidates c LEFT JOIN wa_answers a ON a.id=c.answer_id
              WHERE c.workspace=%s ORDER BY c.updated_at DESC LIMIT 200''',(workspace,)).fetchall()
        return json.loads(json.dumps(rows,default=str))

    def review(self,workspace,candidate_id,action,payload,validate_refs):
        if action not in ('edit','publish','reject','unpublish'): raise ValueError('Invalid review action')
        with self.connection() as c:
            row=c.execute('SELECT * FROM wa_candidates WHERE id=%s AND workspace=%s FOR UPDATE',(candidate_id,workspace)).fetchone()
            if not row: raise ValueError('Candidate not found')
            if payload.get('revision')!=row['revision']: raise ValueError('Candidate changed; refresh before reviewing')
            if action=='edit':
                row.update(question=str(payload.get('question',row['question'])).strip(),answer=str(payload.get('answer',row['answer'])).strip(),
                           conditions=str(payload.get('conditions',row['conditions']))[:2000],privacy_checked=payload.get('privacy_checked') is True)
                if not row['question'] or not row['answer'] or len(row['question'])>4000 or len(row['answer'])>30000:
                    raise ValueError('Invalid question or answer')
                row['state']='pending'
            elif action=='publish':
                if not row['privacy_checked'] or not row['refs'] or not validate_refs(row['refs']):
                    raise ValueError('Privacy review and current valid source references are required')
                row['state']='published'
            else: row['state']='rejected' if action=='reject' else 'unpublished'
            row['revision']+=1
            c.execute('''UPDATE wa_candidates SET question=%s,answer=%s,conditions=%s,privacy_checked=%s,state=%s,
              revision=%s,review_reason=%s,updated_at=now() WHERE id=%s''',
              (row['question'],row['answer'],row['conditions'],row['privacy_checked'],row['state'],row['revision'],str(payload.get('reason',''))[:2000],candidate_id))
            c.execute('INSERT INTO wa_review_events(candidate_id,workspace,action,revision,snapshot) VALUES(%s,%s,%s,%s,%s)',
                      (candidate_id,workspace,action,row['revision'],Jsonb(json.loads(json.dumps(row,default=str)))))
        return {'state':row['state'],'revision':row['revision']}

    def reuse(self,identity,question,allowed_entries,validate_refs,simulation=False):
        with self.connection() as c:
            rows=c.execute("SELECT * FROM wa_candidates WHERE workspace=%s AND state='published' AND simulation=%s",(identity['workspace'],simulation)).fetchall()
        if not rows: return None
        corpus=[list(jieba.cut(row['question'])) for row in rows]
        scores=BM25Okapi(corpus).get_scores(list(jieba.cut(question)))
        for index in sorted(range(len(rows)),key=lambda i:-scores[i])[:5]:
            row=rows[index]
            # Conservative v1: lexical retrieval alone never proves paraphrase equivalence.
            if normalize(row['question'])!=normalize(question) or row['conditions'].strip(): continue
            if any(ref['entry_id'] not in allowed_entries for ref in row['refs']): continue
            if validate_refs(row['refs']): return row
        return None

    def cleanup(self):
        with self.connection() as c:
            c.execute("DELETE FROM wa_candidates WHERE state IN ('pending','rejected') AND updated_at<now()-interval '90 days'")
            c.execute("DELETE FROM wa_feedback WHERE answer_id IN (SELECT id FROM wa_answers WHERE created_at<now()-interval '90 days')")
            c.execute("DELETE FROM wa_answers WHERE created_at<now()-interval '90 days'")
            tables={row['tablename'] for row in c.execute("SELECT tablename FROM pg_tables WHERE schemaname='public'")}
            if 'checkpoints' in tables:
                c.execute("DELETE FROM checkpoints WHERE wa_created_at<now()-interval '90 days'")
                c.execute('''DELETE FROM checkpoint_writes w WHERE wa_created_at<now()-interval '90 days' AND NOT EXISTS
                  (SELECT 1 FROM checkpoints c WHERE c.thread_id=w.thread_id AND c.checkpoint_ns=w.checkpoint_ns AND c.checkpoint_id=w.checkpoint_id)''')
                c.execute('''DELETE FROM checkpoint_blobs b WHERE wa_created_at<now()-interval '90 days' AND NOT EXISTS
                  (SELECT 1 FROM checkpoints c WHERE c.thread_id=b.thread_id AND c.checkpoint_ns=b.checkpoint_ns
                   AND c.checkpoint->'channel_versions'->>b.channel=b.version)''')
            for table in ('checkpoint_writes','checkpoint_blobs','checkpoints'):
                if table in tables:
                    c.execute(f"DELETE FROM {table} WHERE thread_id IN (SELECT session_key FROM wa_sessions WHERE updated_at<now()-interval '90 days')")
            c.execute("DELETE FROM wa_sessions WHERE updated_at<now()-interval '90 days'")
            c.execute("DELETE FROM wa_feedback_events WHERE created_at<now()-interval '90 days'")
