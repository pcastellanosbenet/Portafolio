"""Qdrant persistence and dense vector search."""

from __future__ import annotations

import uuid
from typing import Any

import numpy as np
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from src.models import Chunk, RetrievedChunk, SearchFilters

POINT_NAMESPACE = uuid.UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def chunk_point_id(chunk_id: str) -> str:
    """Convert a human-readable chunk id into a deterministic Qdrant UUID."""
    return str(uuid.uuid5(POINT_NAMESPACE, chunk_id))


class QdrantIndex:
    def __init__(
        self,
        collection_name: str,
        *,
        url: str | None = None,
        path: str | None = None,
        timeout: int = 60,
        client: QdrantClient | None = None,
    ) -> None:
        self.collection_name = collection_name
        if client is not None:
            self.client = client
        elif url:
            self.client = QdrantClient(url=url, timeout=timeout)
        elif path:
            self.client = QdrantClient(path=path)
        else:
            raise ValueError("Qdrant necesita url, path o un cliente inyectado.")

    def ensure_collection(self, dimension: int, *, recreate: bool = False) -> None:
        exists = self.client.collection_exists(self.collection_name)
        if exists and recreate:
            self.client.delete_collection(self.collection_name)
            exists = False
        if not exists:
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
            )

    def delete_collection(self) -> None:
        if self.client.collection_exists(self.collection_name):
            self.client.delete_collection(self.collection_name)

    def count(self) -> int:
        return int(self.client.count(self.collection_name, exact=True).count)

    def vector_size(self) -> int | None:
        info = self.client.get_collection(self.collection_name)
        vectors = info.config.params.vectors
        if hasattr(vectors, "size"):
            return int(vectors.size)
        return None

    def existing_chunk_ids(self, chunk_ids: list[str]) -> set[str]:
        if not chunk_ids:
            return set()
        ids = [chunk_point_id(chunk_id) for chunk_id in chunk_ids]
        points = self.client.retrieve(
            collection_name=self.collection_name,
            ids=ids,
            with_payload=["chunk_id"],
            with_vectors=False,
        )
        return {
            str(point.payload.get("chunk_id"))
            for point in points
            if point.payload and point.payload.get("chunk_id")
        }

    def upsert_chunks(
        self,
        chunks: list[Chunk],
        vectors: np.ndarray,
        *,
        batch_size: int = 64,
    ) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks y vectors deben tener la misma longitud")
        for start in range(0, len(chunks), batch_size):
            points = [
                PointStruct(
                    id=chunk_point_id(chunk.chunk_id),
                    vector=vector.tolist(),
                    payload=chunk.to_dict(),
                )
                for chunk, vector in zip(
                    chunks[start : start + batch_size],
                    vectors[start : start + batch_size],
                    strict=True,
                )
            ]
            self.client.upsert(
                collection_name=self.collection_name,
                points=points,
                wait=True,
            )

    def _build_filter(self, filters: SearchFilters | None) -> Filter | None:
        if not filters or filters.is_empty():
            return None
        must: list[Any] = []
        if filters.volume_number:
            must.append(
                FieldCondition(
                    key="volume_number",
                    match=MatchValue(value=filters.volume_number),
                )
            )
        if filters.doc_id:
            must.append(
                FieldCondition(key="doc_id", match=MatchValue(value=filters.doc_id))
            )
        if filters.doc_number:
            must.append(
                FieldCondition(
                    key="doc_number",
                    match=MatchValue(value=filters.doc_number),
                )
            )
        if filters.content_type:
            must.append(
                FieldCondition(
                    key="content_type",
                    match=MatchValue(value=filters.content_type),
                )
            )
        if filters.entity:
            must.append(
                FieldCondition(
                    key="entities",
                    match=MatchAny(any=[filters.entity]),
                )
            )
        return Filter(must=must) if must else None

    def search(
        self,
        vector: np.ndarray,
        *,
        filters: SearchFilters | None = None,
        limit: int = 30,
    ) -> list[RetrievedChunk]:
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=vector.tolist(),
            query_filter=self._build_filter(filters),
            limit=limit,
            with_payload=True,
            with_vectors=False,
        )
        results: list[RetrievedChunk] = []
        for point in response.points:
            if not point.payload:
                continue
            chunk = Chunk.from_dict(point.payload)
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=float(point.score),
                    dense_score=float(point.score),
                )
            )
        return results

    def close(self) -> None:
        self.client.close()
