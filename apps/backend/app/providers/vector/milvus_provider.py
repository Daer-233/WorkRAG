"""Milvus adapter for the dense, sparse and scalar index used by both libraries."""

import json
from uuid import UUID

from app.core.config import settings
from app.providers.vector.base import SearchFilter, VectorHit, VectorRecord
from app.providers.vector.qdrant_provider import QdrantVectorProvider


def _literal(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def filter_expression(filters: SearchFilter) -> str:
    clauses = [f'payload["chunk_level"] == {_literal(filters.chunk_level)}']
    if filters.enforce_roles:
        access = 'payload["access_open"] == true'
        if filters.principal_roles:
            access += f' or json_contains_any(payload["access_roles"], {_literal(filters.principal_roles)})'
        clauses.append(f'({access})')
    if filters.project_id is not None:
        clauses.append(f'payload["project_id"] == {_literal(filters.project_id)}')
    for key, values in (
        ('file_type', filters.file_types), ('chunk_type', filters.chunk_types),
        ('content_origin', filters.content_origins), ('document_version_id', filters.document_version_ids),
    ):
        if values:
            clauses.append(f'payload["{key}"] in {_literal(values)}')
    if filters.point_ids:
        clauses.append(f'id in {_literal(filters.point_ids)}')
    if filters.page_start is not None:
        clauses.append(f'payload["page_end"] >= {_literal(filters.page_start)}')
    if filters.page_end is not None:
        clauses.append(f'payload["page_start"] <= {_literal(filters.page_end)}')
    return ' and '.join(clauses)


class MilvusVectorProvider:
    provider_name = 'milvus'

    def __init__(self, *, uri=None, collection_name=None):
        from pymilvus import MilvusClient

        self.collection_name = collection_name or settings.milvus_collection
        if not self.collection_name:
            raise ValueError('MILVUS_COLLECTION must identify the application collection')
        self.client = MilvusClient(uri=uri or settings.milvus_uri, timeout=30)

    def health(self) -> bool:
        try:
            return bool(self.client.has_collection(self.collection_name))
        except Exception:
            return False

    def ensure_collection(self, dense_dimension: int) -> None:
        from pymilvus import DataType

        if not self.client.has_collection(self.collection_name):
            schema = self.client.create_schema(auto_id=False, enable_dynamic_field=False)
            schema.add_field('id', DataType.VARCHAR, is_primary=True, max_length=36)
            schema.add_field('dense', DataType.FLOAT_VECTOR, dim=dense_dimension)
            schema.add_field('sparse', DataType.SPARSE_FLOAT_VECTOR, nullable=True)
            schema.add_field('payload', DataType.JSON)
            indexes = self.client.prepare_index_params()
            indexes.add_index('dense', index_type='AUTOINDEX', metric_type='COSINE')
            indexes.add_index('sparse', index_type='SPARSE_INVERTED_INDEX', metric_type='IP')
            self.client.create_collection(self.collection_name, schema=schema, index_params=indexes)
        description = self.client.describe_collection(self.collection_name)
        fields = {field['name']: field for field in description['fields']}
        expected = {'id': DataType.VARCHAR, 'dense': DataType.FLOAT_VECTOR,
                    'sparse': DataType.SPARSE_FLOAT_VECTOR, 'payload': DataType.JSON}
        if (any(fields.get(name, {}).get('type') != kind for name, kind in expected.items())
                or not fields['id'].get('is_primary')
                or int(fields['dense']['params']['dim']) != dense_dimension):
            raise ValueError('Milvus collection schema does not match the vector index')

    def upsert_chunks(self, records: list[VectorRecord], dense_dimension: int) -> None:
        if not records:
            return
        self.ensure_collection(dense_dimension)
        for start in range(0, len(records), 100):
            rows = [{
                'id': str(UUID(record.point_id)), 'dense': record.dense_vector,
                'sparse': dict(zip(record.sparse_indices, record.sparse_values, strict=True)) or None,
                'payload': record.payload,
            } for record in records[start:start + 100]]
            result = self.client.upsert(self.collection_name, rows)
            if result['upsert_count'] != len(rows):
                raise RuntimeError('Milvus did not acknowledge the complete upsert batch')

    def delete_chunks(self, chunk_ids: list[str]) -> None:
        ids = list(dict.fromkeys(str(UUID(value)) for value in chunk_ids))
        for start in range(0, len(ids), 100):
            self.client.delete(self.collection_name, ids=ids[start:start + 100])

    def search_lane(self, kind, vector, search_filter, limit):
        if search_filter.document_version_ids == [] or search_filter.point_ids == [] or not vector:
            return []
        metric = {'dense': 'COSINE', 'sparse': 'IP'}[kind]
        result = self.client.search(
            self.collection_name, data=[vector], anns_field=kind, limit=limit,
            filter=filter_expression(search_filter), search_params={'metric_type': metric},
            output_fields=['payload'], consistency_level='Strong',
        )
        return [VectorHit(str(hit['id']), float(hit['distance']), hit['entity']['payload'])
                for hit in result[0]]

    def hybrid_search(self, *, dense_vector, sparse_indices, sparse_values, search_filter, limit):
        dense = self.search_lane('dense', dense_vector, search_filter, limit)
        sparse = self.search_lane('sparse', dict(zip(sparse_indices, sparse_values, strict=True)), search_filter, limit)
        return QdrantVectorProvider._rrf_fuse(dense, sparse)
