"""Register a verified vector snapshot and atomically select it after stopping writers."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
from shutil import copy2
import socket
from datetime import datetime

import psycopg
from dotenv import dotenv_values
from psycopg.conninfo import conninfo_to_dict

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('snapshot', ROOT / 'scripts/migrate-qdrant-milvus-snapshot.py')
snapshot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(snapshot)


def prepare(library, manifest_path):
    manual = library == 'manual'
    config = ROOT / 'instances/manuals/.env' if manual else Path('I:/Design_RAG/.env')
    source_name = 'manual_rag_chunks_v1' if manual else 'design_rag_chunks_v1'
    database = 'manual_rag' if manual else 'design_rag'
    port = 8060 if manual else 8030
    with socket.socket() as probe:
        probe.settimeout(2)
        if probe.connect_ex(('127.0.0.1', port)) == 0:
            raise RuntimeError('Stop the application backend before preparing cutover')
    env = dotenv_values(config)
    if env.get('VECTOR_PROVIDER', 'qdrant').lower() != 'qdrant' or env.get('QDRANT_COLLECTION', source_name) != source_name:
        raise RuntimeError('Unexpected source configuration')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))['collections'][source_name]
    target_name = manifest['destination']
    prefix = 'wk_manual_snapshot_' if manual else 'wk_design_snapshot_'
    if (not target_name.startswith(prefix) or manifest['state'] != 'snapshot_verified'
            or manifest.get('full_rows_verified') != manifest['destination_count'] or manifest.get('orphan_ids')):
        raise RuntimeError('The intended destination requires full verification')

    with snapshot.httpx.Client(trust_env=False, timeout=30) as http:
        points = snapshot.read_source(http, source_name)
    if snapshot.digest(points) != manifest['source_sha256']:
        raise RuntimeError('Source has changed since the snapshot; refresh it before cutover')
    ids = {str(point['id']) for point in points}
    target = snapshot.MilvusClient(uri='http://127.0.0.1:19530', timeout=30)
    count = target.query(target_name, filter='', output_fields=['count(*)'], consistency_level='Strong')[0]['count(*)']
    if count != len(ids):
        raise RuntimeError('Target entity count changed since verification')

    dsn = env['POSTGRES_DSN'].replace('postgresql+psycopg://', 'postgresql://', 1)
    identity = conninfo_to_dict(dsn)
    if identity.get('dbname') != database or identity.get('host') not in {'127.0.0.1', 'localhost', '::1'}:
        raise RuntimeError('Unexpected authority database')

    backup_dir = ROOT / 'backups/milvus-cutover' / datetime.now().strftime('%Y%m%d-%H%M%S')
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / f'{library}.env.before'
    copy2(config, backup)
    with psycopg.connect(dsn, connect_timeout=10) as db:
        records = db.execute('''SELECT point_id,index_status FROM vector_index_records
            WHERE provider_name='qdrant' AND collection_name=%s FOR SHARE''', (source_name,)).fetchall()
        indexed_ids = {point_id for point_id, state in records if state == 'indexed'}
        if indexed_ids != ids:
            raise RuntimeError('PostgreSQL indexed IDs and the vector snapshot differ')
        db.execute('''INSERT INTO vector_index_records
            (id,chunk_id,provider_name,collection_name,point_id,embedding_model_version_id,index_status,indexed_at,last_error)
            SELECT gen_random_uuid(),chunk_id,'milvus',%s,point_id,embedding_model_version_id,index_status,indexed_at,last_error
            FROM vector_index_records WHERE provider_name='qdrant' AND collection_name=%s
            ON CONFLICT (provider_name,collection_name,chunk_id) DO NOTHING''', (target_name, source_name))
        target_records = db.execute('''SELECT point_id,index_status FROM vector_index_records
            WHERE provider_name='milvus' AND collection_name=%s''', (target_name,)).fetchall()
        if sorted(target_records) != sorted(records):
            raise RuntimeError('Target ledger differs from source ledger')

    values = {'VECTOR_PROVIDER': 'milvus', 'MILVUS_URI': 'http://127.0.0.1:19530',
              'MILVUS_COLLECTION': target_name, 'MILVUS_SDK_PATH': f'"{(ROOT / "data/milvus-sdk").as_posix()}"'}
    content = config.read_text(encoding='utf-8-sig')
    lines = [line for line in content.splitlines()
             if not (re.match(r'^\s*(?:export\s+)?([A-Z_]+)\s*=', line) and
                     re.match(r'^\s*(?:export\s+)?([A-Z_]+)\s*=', line)[1] in values)]
    temp = config.with_name('.env.milvus-pending')
    temp.write_text('\n'.join(lines + [f'{key}={value}' for key, value in values.items()]) + '\n', encoding='utf-8')
    os.replace(temp, config)
    print(json.dumps({'library': library, 'collection': target_name, 'indexed': len(ids),
                      'ledger_rows': len(records), 'backup': str(backup)}, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('library', choices=('manual', 'design'))
    parser.add_argument('manifest', type=Path)
    args = parser.parse_args()
    prepare(args.library, args.manifest)
