"""Hybrid dense + BM25 retrieval with reciprocal rank fusion."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.bm25 import BM25Index
from src.embeddings import Embedder
from src.models import Chunk, RetrievedChunk, SearchFilters
from src.rerank import Reranker
from src.text import estimate_tokens, tokenize

logger = logging.getLogger(__name__)


class ChunkStore:
    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self.by_id = {chunk.chunk_id: chunk for chunk in chunks}
        self.by_section: dict[tuple[str, str], list[Chunk]] = {}
        for chunk in chunks:
            self.by_section.setdefault((chunk.doc_id, chunk.section_path), []).append(chunk)
        for section_chunks in self.by_section.values():
            section_chunks.sort(key=lambda chunk: chunk.chunk_id)

    @classmethod
    def load(cls, path: Path) -> ChunkStore:
        if not path.exists():
            return cls([])
        chunks: list[Chunk] = []
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    chunks.append(Chunk.from_dict(json.loads(line)))
        return cls(chunks)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as handle:
            for chunk in self.chunks:
                handle.write(json.dumps(chunk.to_dict(), ensure_ascii=False) + "\n")

    def get(self, chunk_id: str) -> Chunk | None:
        return self.by_id.get(chunk_id)

    def documents(self) -> list[str]:
        return sorted({chunk.doc_id for chunk in self.chunks})

    def section_neighbors(self, chunk: Chunk) -> list[Chunk]:
        siblings = self.by_section.get((chunk.doc_id, chunk.section_path), [])
        try:
            index = next(
                position
                for position, candidate in enumerate(siblings)
                if candidate.chunk_id == chunk.chunk_id
            )
        except StopIteration:
            return []
        neighbors: list[Chunk] = []
        if index > 0:
            neighbors.append(siblings[index - 1])
        if index + 1 < len(siblings):
            neighbors.append(siblings[index + 1])
        return neighbors


def _matches_filters(chunk: Chunk, filters: SearchFilters | None) -> bool:
    if not filters or filters.is_empty():
        return True
    if filters.volume_number and chunk.volume_number != filters.volume_number:
        return False
    if filters.doc_id and chunk.doc_id != filters.doc_id:
        return False
    if filters.doc_number and chunk.doc_number != filters.doc_number:
        return False
    if filters.content_type and chunk.content_type != filters.content_type:
        return False
    if filters.entity and filters.entity not in chunk.entities:
        return False
    return True


class Retriever:
    """Fuse BM25 and dense rankings, then optionally rerank the candidates."""

    def __init__(
        self,
        store: ChunkStore,
        index: Any,
        embedder: Embedder,
        reranker: Reranker,
        *,
        rrf_k: int = 60,
        candidate_k: int = 30,
        rerank_k: int = 20,
        top_k: int = 8,
    ) -> None:
        self.store = store
        self.index = index
        self.embedder = embedder
        self.reranker = reranker
        self.rrf_k = rrf_k
        self.candidate_k = candidate_k
        self.rerank_k = rerank_k
        self.top_k = top_k
        self.bm25 = BM25Index()
        self.bm25.fit([tokenize(chunk.text) for chunk in store.chunks])

    def _bm25_candidates(
        self,
        query: str,
        filters: SearchFilters | None,
        limit: int,
    ) -> list[tuple[Chunk, float]]:
        tokens = tokenize(query)
        ranked = self.bm25.top_n(tokens, n=max(limit * 4, limit))
        results: list[tuple[Chunk, float]] = []
        for index, score in ranked:
            chunk = self.store.chunks[index]
            if _matches_filters(chunk, filters):
                results.append((chunk, score))
            if len(results) >= limit:
                break
        return results

    def search(
        self,
        query: str,
        *,
        filters: SearchFilters | None = None,
        top_k: int | None = None,
        candidate_k: int | None = None,
        use_reranker: bool = True,
    ) -> list[RetrievedChunk]:
        top_k = top_k or self.top_k
        candidate_k = candidate_k or self.candidate_k
        fused: dict[str, RetrievedChunk] = {}
        rrf_scores: dict[str, float] = {}

        def add_candidate(
            chunk: Chunk,
            *,
            rank: int,
            dense_score: float | None = None,
            bm25_score: float | None = None,
        ) -> None:
            key = chunk.chunk_id
            fused.setdefault(key, RetrievedChunk(chunk=chunk, score=0.0))
            item = fused[key]
            if dense_score is not None:
                item.dense_score = dense_score
            if bm25_score is not None:
                item.bm25_score = bm25_score
            rrf_scores[key] = rrf_scores.get(key, 0.0) + 1.0 / (self.rrf_k + rank + 1)

        for rank, (chunk, score) in enumerate(
            self._bm25_candidates(query, filters, candidate_k)
        ):
            add_candidate(chunk, rank=rank, bm25_score=score)

        try:
            dense_results = self.index.search(
                self.embedder.embed_query(query),
                filters=filters,
                limit=candidate_k,
            )
        except Exception as error:  # pragma: no cover - depends on Qdrant state
            logger.warning("Búsqueda densa no disponible: %s", error)
            dense_results = []
        for rank, result in enumerate(dense_results):
            add_candidate(
                result.chunk,
                rank=rank,
                dense_score=result.dense_score,
            )

        for key, item in fused.items():
            item.score = rrf_scores.get(key, 0.0)

        candidates = sorted(fused.values(), key=lambda item: item.score, reverse=True)
        candidates = candidates[: self.rerank_k if use_reranker else top_k]

        if use_reranker and candidates:
            rerank_scores = self.reranker.score(
                query, [item.chunk.text for item in candidates]
            )
            if rerank_scores is not None:
                for item, score in zip(candidates, rerank_scores, strict=True):
                    item.rerank_score = score
                    item.score = score
                candidates.sort(key=lambda item: item.score, reverse=True)

        results = candidates[:top_k]
        for rank, result in enumerate(results):
            result.rank = rank
        return results

    def expand_context(
        self,
        results: list[RetrievedChunk],
        *,
        max_tokens: int = 3000,
    ) -> list[RetrievedChunk]:
        """Add adjacent chunks from the same section within a token budget."""
        expanded: list[RetrievedChunk] = []
        seen: set[str] = set()
        used = 0
        for result in results:
            candidates = [result.chunk, *self.store.section_neighbors(result.chunk)]
            for chunk in candidates:
                if chunk.chunk_id in seen:
                    continue
                cost = max(1, chunk.token_count or estimate_tokens(chunk.text))
                if used + cost > max_tokens:
                    break
                expanded.append(
                    RetrievedChunk(
                        chunk=chunk,
                        score=result.score,
                        dense_score=result.dense_score,
                        bm25_score=result.bm25_score,
                        rerank_score=result.rerank_score,
                        rank=result.rank,
                    )
                )
                seen.add(chunk.chunk_id)
                used += cost
            if used >= max_tokens:
                break
        return expanded
