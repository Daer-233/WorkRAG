"""Vector provider factory. Business services only depend on the shared contract."""

from functools import lru_cache

from app.core.config import settings
from app.providers.vector.base import VectorProvider
from app.providers.vector.qdrant_provider import QdrantVectorProvider


def vector_identity() -> tuple[str, str]:
    provider = settings.vector_provider.lower()
    if provider == "qdrant":
        return provider, settings.qdrant_collection
    if provider == "milvus" and settings.milvus_collection:
        return provider, settings.milvus_collection
    raise ValueError("Invalid vector provider or collection configuration")


@lru_cache
def get_vector_provider() -> VectorProvider:
    if settings.vector_provider.lower() == "qdrant":
        return QdrantVectorProvider()
    if settings.vector_provider.lower() == "milvus":
        from app.providers.vector.milvus_provider import MilvusVectorProvider

        return MilvusVectorProvider()
    raise ValueError(f"Unsupported VECTOR_PROVIDER: {settings.vector_provider}")
