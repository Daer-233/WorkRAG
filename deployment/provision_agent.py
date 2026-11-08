"""Provision isolated workflow database and private runtime configuration."""
from pathlib import Path
import secrets
import sys
import json
import subprocess

import psycopg
from psycopg import sql
from dotenv import dotenv_values
from langgraph.checkpoint.postgres import PostgresSaver

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'apps/workrag-agent'))
from workrag_agent.store import Store

private=ROOT/'data/manuals/runtime/agent.env'
if not private.exists():
    password=secrets.token_urlsafe(32)
    config={'WORKRAG_AGENT_DSN':f'postgresql://workrag_agent:{password}@127.0.0.1:5432/workrag_agent',
            'WORKRAG_SCOPE_SECRET':secrets.token_urlsafe(48),'WORKRAG_MCP_ACCESS_TOKEN':secrets.token_urlsafe(48)}
    original=dotenv_values(ROOT/'instances/manuals/.env')
    with psycopg.connect(original['POSTGRES_DSN'],autocommit=True) as c:
        if c.execute("SELECT 1 FROM pg_roles WHERE rolname='workrag_agent'").fetchone():
            raise RuntimeError('Existing workflow role without private configuration; refusing to replace it')
        c.execute(sql.SQL('CREATE ROLE workrag_agent LOGIN PASSWORD {}').format(sql.Literal(password)))
        c.execute('CREATE DATABASE workrag_agent OWNER workrag_agent')
    private.write_text(''.join(k+'='+v+'\n' for k,v in config.items()),encoding='utf-8')
config=dict(dotenv_values(private))
store=Store(config['WORKRAG_AGENT_DSN']); store.setup()
with PostgresSaver.from_conn_string(config['WORKRAG_AGENT_DSN']) as saver: saver.setup()
store.setup()
print('Isolated workrag_agent database and private configuration ready.')
