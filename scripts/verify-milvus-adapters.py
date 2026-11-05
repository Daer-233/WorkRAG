"""Application-level acceptance against a disposable PostgreSQL on port 15432."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from time import perf_counter
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
args = argparse.ArgumentParser(description=__doc__)
args.add_argument('library', choices=('manual', 'design'))
args.add_argument('--backend', choices=('milvus', 'qdrant'), default='milvus')
args = args.parse_args()
code = ROOT if args.library == 'manual' else Path('I:/Design_RAG')
sys.path[:0] = [str(code / 'apps/backend'), str(ROOT / 'data/milvus-sdk')]
collection = f'wk_{args.library}_acceptance_{uuid4().hex[:12]}'
database = 'manual_rag' if args.library == 'manual' else 'design_rag'
os.environ.update(VECTOR_PROVIDER=args.backend, MILVUS_COLLECTION=collection, QDRANT_COLLECTION=collection,
                  MILVUS_URI='http://127.0.0.1:19530',
                  POSTGRES_DSN=f'postgresql://manual_rag@127.0.0.1:15432/{database}',
                  DESIGN_RAG_ENV_FILE=str(ROOT / 'data/manuals/runtime/milvus-acceptance.env'))

import psycopg
from app.clients.inference import ModelIdentity
from app.db.connection import connection
from app.db.migrations import apply_migrations
from app.providers.vector.factory import get_vector_provider

measurements = {}


def existing_ids(provider, ids):
    if args.backend == 'milvus':
        rows = provider.client.get(collection, ids=ids, consistency_level='Strong')
        return {str(row['id']) for row in rows}
    rows = provider.client.retrieve(collection, ids=ids, with_payload=False)
    return {str(row.id) for row in rows}


class Embedding:
    def model_identity(self):
        return ModelIdentity('embedding', 'test', 'milvus-acceptance', 'fixture', None, {})

    def embed(self, texts):
        return {'dense_dimension': 1024, 'dense_vectors': [[1.0] + [0.0] * 1023 for _ in texts],
                'sparse_vectors': [{'indices': [7], 'values': [1.0]} for _ in texts]}

    embed_many = embed


class Rerank:
    def rerank(self, question, texts):
        return [{'index': i, 'score': 5.0} for i in range(len(texts))]


def manual(provider):
    from app.manuals import service as module
    from app.manuals.departments import Scope, permitted_for_context, save_scopes
    from app.manuals.groups import suggest_groups
    from app.manuals.retrieval import HybridRetriever

    with connection() as db:
        db.execute((code / 'apps/backend/app/manuals/schema.sql').read_text(encoding='utf-8'))
        db.execute((code / 'apps/backend/app/manuals/departments.sql').read_text(encoding='utf-8'))
        department = uuid4()
        db.execute('INSERT INTO manual_departments VALUES (%s, %s, %s)',
                   (department, collection, collection))
    module.EmbeddingClient = Embedding
    service = module.ManualService(retriever=HybridRetriever(Embedding(), Rerank()))
    category = service.store.create_category('Milvus ' + collection)

    def add(version, interrupt=False):
        entry = service.store.create(SimpleNamespace(title='Synthetic access procedure',
            category_id=category['id'], product='fixture', version=version, family_key=collection))
        steps = [{'order': 1, 'instruction': 'Synthetic access procedure', 'page': 1, 'asset_ids': []}]
        groups = [dict(group, confirmed=True) for group in suggest_groups(steps, entry['title'])]
        service.save_steps(entry['id'], steps, groups)
        if interrupt:
            original = provider.upsert_chunks

            def interrupted(records, dimension):
                original(records, dimension)
                raise RuntimeError('Synthetic interruption')

            provider.upsert_chunks = interrupted
            try:
                service.index_entry(entry['id'])
            except RuntimeError as error:
                assert str(error) == 'Synthetic interruption'
                assert service.store.get(entry['id'])['index_status'] == 'failed'
            else:
                raise AssertionError('Expected interrupted indexing to fail')
            finally:
                provider.upsert_chunks = original
        service.index_entry(entry['id'])
        service.index_entry(entry['id'])
        return service.store.publish(entry['id'])

    old, replacement, other_version = add('1', interrupt=True), add('1'), add('2')
    save_scopes([row['id'] for row in (old, replacement, other_version)],
                Scope(department_ids=[department], confirmed=True))
    allowed_context, denied_context = uuid4(), uuid4()
    with connection() as db:
        for context, department_ids in [(allowed_context, [collection]), (denied_context, [str(uuid4())])]:
            db.execute("INSERT INTO manual_department_contexts VALUES (%s, %s, now() + interval '10 minutes')",
                       (context, department_ids))
    ids = permitted_for_context(allowed_context)
    other_department = permitted_for_context(denied_context)
    assert ids == {str(row['id']) for row in (old, replacement, other_version)}
    assert not other_department
    question = 'Synthetic access procedure'
    answer = service.ask(question, category_id=category['id'], source_only=True, permitted_entry_ids=ids)
    assert answer['status'] == 'choose_version'
    assert {str(row['id']) for row in answer['options']} == ids - {str(old['id'])}
    started = perf_counter()
    selected = service.ask(question, pinned_version='1', source_only=True,
                           permitted_entry_ids={str(replacement['id'])}, department_context=allowed_context)
    assert {str(row['entry']['id']) for row in selected['sources']} == {str(replacement['id'])}
    assert selected['retrieval_metrics']['dense_count'] == selected['retrieval_metrics']['sparse_count'] == 1
    measurements['pinned_version'] = {'dense_hits': 1, 'sparse_hits': 1, 'required_evidence_hits': 1,
                                      'elapsed_ms': round((perf_counter() - started) * 1000, 2)}
    assert not service.ask(question, source_only=True, permitted_entry_ids=other_department)['sources']
    save_scopes([replacement['id']], Scope())
    assert not service.ask(question, pinned_version='1', source_only=True,
        permitted_entry_ids={str(replacement['id'])}, department_context=allowed_context)['sources']
    stale, keep = (str(row['data']['steps'][0]['evidence_id']) for row in (old, replacement))
    provider.delete_chunks([stale])
    provider.delete_chunks([stale])
    assert existing_ids(provider, [stale, keep]) == {keep}
    return ['manual normal indexing', 'interrupted index retry', 'repeat upsert', 'same-version replacement',
            'version choice', 'pinned version', 'PostgreSQL department scope', 'dense and sparse recall', 'repeat deletion']


def design(provider):
    from app.api.schemas import IngestRequest, SearchFilters
    from app.repositories.rag_repository import RagRepository
    from app.services.access_policy import AccessDeniedError, AccessPolicy, Principal
    from app.services.rag_service import IngestionService, SearchService

    repository = RagRepository()
    ingest = IngestionService(repository, Embedding())
    search = SearchService(repository, Embedding(), Rerank(), AccessPolicy())

    def add(name):
        body = IngestRequest(project={'external_key': collection, 'name': 'Fixture'},
            document={'external_key': 'versions', 'source_uri': 'fixture://versions',
                      'file_name': 'fixture.pdf', 'file_type': 'pdf'},
            parser={'provider': 'test', 'model': 'fixture'},
            chunks=[{'ordinal': 0, 'content': name, 'access_scope': {'roles': ['staff']},
                     'children': [{'ordinal': 0, 'content': name, 'page_start': 1, 'page_end': 1}]}])
        return ingest.ingest(body.model_dump(mode='python', exclude_none=True))

    old, latest = add('old version'), add('latest version')
    assert old['index_status'] == latest['index_status'] == 'indexed'
    project = latest['project_id']

    def run(version=None, roles=('staff',), project_id=project):
        filters = SearchFilters(document_version_id=version, file_types=['pdf'], page_start=1, page_end=1)
        started = perf_counter()
        result = search.search(query='version', project_id=project_id,
            principal_raw=Principal('test', {project}, set(roles)), evidence_top_k=8,
            retrieval_filters=filters.model_dump(exclude_none=True), include_images=False)
        rows = result['results']
        if rows:
            scores = [row['scores'] for row in rows]
            measurements.setdefault('history' if version else 'latest', {
                'dense_hits': sum(score.get('dense') is not None for score in scores),
                'sparse_hits': sum(score.get('sparse') is not None for score in scores),
                'required_evidence_hits': len(rows), 'elapsed_ms': round((perf_counter() - started) * 1000, 2),
            })
        return {row['chunk_id'] for row in rows}

    assert run() == set(latest['child_chunk_ids'])
    assert run(old['document_version_id']) == set(old['child_chunk_ids'])
    assert not run(roles=())
    try:
        run(project_id=str(uuid4()))
    except AccessDeniedError:
        pass
    else:
        raise AssertionError('Cross-project query should be rejected')

    with connection() as db:
        db.execute('UPDATE chunks SET access_scope = %s::jsonb WHERE id = %s',
                   ('{"roles":["other"]}', latest['parent_chunk_ids'][0]))
    assert not run(), 'The PostgreSQL parent check must override the vector payload'

    write = provider.upsert_chunks
    def interrupted(records, dimension):
        write(records[-1:], dimension)
        raise RuntimeError('Synthetic interruption')
    provider.upsert_chunks = interrupted
    try:
        pending = add('not yet indexed')
    finally:
        provider.upsert_chunks = write
    assert pending['index_status'] == 'failed' and not run()
    assert existing_ids(provider, pending['child_chunk_ids']) == set(pending['child_chunk_ids'])
    assert run(old['document_version_id']) == set(old['child_chunk_ids'])
    spec = importlib.util.spec_from_file_location('reindex', code / 'scripts/reindex-pending-vectors.py')
    reindex = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reindex)
    reindex.EmbeddingClient = Embedding
    argv = sys.argv
    try:
        sys.argv = [argv[0], '--document-version-id', pending['document_version_id']]
        assert reindex.main() == 0
    finally:
        sys.argv = argv
    assert run() == set(pending['child_chunk_ids'])
    stale, keep = old['child_chunk_ids'][0], latest['child_chunk_ids'][0]
    provider.delete_chunks([stale])
    provider.delete_chunks([stale])
    assert not run(old['document_version_id'])
    assert existing_ids(provider, [stale, keep]) == {keep}
    return ['design normal ingestion', 'latest version', 'authorized history', 'project and role isolation',
            'authoritative parent revocation', 'failed newest index', 'scoped reindex retry', 'repeat deletion']


if database == 'design_rag':
    with psycopg.connect('postgresql://manual_rag@127.0.0.1:15432/postgres', autocommit=True) as db:
        if not db.execute('SELECT 1 FROM pg_database WHERE datname = %s', (database,)).fetchone():
            db.execute('CREATE DATABASE design_rag')
apply_migrations()
provider = get_vector_provider()
try:
    checks = (manual if args.library == 'manual' else design)(provider)
    report = {'library': args.library, 'backend': args.backend, 'passed': True,
              'checks': checks, 'measurements': measurements, 'model_inputs': 'synthetic deterministic fixtures'}
    path = ROOT / 'data/manuals/runtime/milvus-migration' / f'acceptance-{args.library}-{args.backend}.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False))
finally:
    exists = provider.client.has_collection if args.backend == 'milvus' else provider.client.collection_exists
    if exists(collection) and args.backend == 'milvus':
        provider.client.drop_collection(collection)
    elif exists(collection):
        provider.client.delete_collection(collection)
