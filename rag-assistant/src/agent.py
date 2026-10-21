"""A bounded, deterministic retrieval agent for the KNX standard."""

from __future__ import annotations

from typing import Any

from src.answer import AnswerService
from src.entities import EntityCatalog, QueryPlan, build_query_plan
from src.models import AgentAnswer, RetrievedChunk, SearchFilters
from src.retrieve import Retriever


def _merge_filters(
    user_filters: SearchFilters | None,
    plan: QueryPlan,
) -> SearchFilters:
    user = user_filters or SearchFilters()
    return SearchFilters(
        volume_number=user.volume_number or plan.filters.volume_number,
        doc_id=user.doc_id,
        doc_number=user.doc_number or plan.filters.doc_number,
        content_type=user.content_type,
        entity=user.entity,
    )


class KNXAgent:
    """Route, retrieve, expand and answer with at most two retrieval attempts."""

    def __init__(
        self,
        retriever: Retriever,
        answer_service: AnswerService,
        catalog: EntityCatalog,
        *,
        top_k: int = 8,
        max_context_tokens: int = 3000,
    ) -> None:
        self.retriever = retriever
        self.answer_service = answer_service
        self.catalog = catalog
        self.top_k = top_k
        self.max_context_tokens = max_context_tokens

    def _exact_results(self, plan: QueryPlan) -> list[RetrievedChunk]:
        records = self.catalog.lookup_many(plan.entities)
        results: list[RetrievedChunk] = []
        seen: set[str] = set()
        for record in records:
            if record.chunk_id in seen:
                continue
            chunk = self.retriever.store.get(record.chunk_id)
            if chunk is None:
                continue
            seen.add(record.chunk_id)
            results.append(
                RetrievedChunk(
                    chunk=chunk,
                    score=1.0,
                    dense_score=None,
                    bm25_score=None,
                    rerank_score=None,
                    rank=len(results),
                )
            )
        return results

    def run(
        self,
        question: str,
        *,
        filters: SearchFilters | None = None,
        top_k: int | None = None,
    ) -> AgentAnswer:
        plan = build_query_plan(question)
        effective_filters = _merge_filters(filters, plan)
        trace: list[dict[str, Any]] = [
            {
                "step": "plan",
                "query_type": plan.query_type,
                "entities": plan.entities,
                "filters": effective_filters.__dict__,
                "expanded_query": plan.expanded,
            }
        ]

        exact = self._exact_results(plan)
        if exact:
            trace.append(
                {
                    "step": "exact_lookup",
                    "matches": len(exact),
                    "chunk_ids": [result.chunk.chunk_id for result in exact],
                }
            )

        results = self.retriever.search(
            plan.expanded,
            filters=effective_filters,
            top_k=top_k or self.top_k,
        )
        trace.append(
            {
                "step": "retrieve",
                "filters": effective_filters.__dict__,
                "results": len(results),
                "top_scores": [round(result.score, 4) for result in results[:5]],
            }
        )

        if len(results) < 2 and not effective_filters.is_empty():
            results = self.retriever.search(
                plan.expanded,
                filters=None,
                top_k=top_k or self.top_k,
            )
            trace.append(
                {
                    "step": "retrieve_broadened",
                    "results": len(results),
                    "top_scores": [round(result.score, 4) for result in results[:5]],
                }
            )

        merged: list[RetrievedChunk] = []
        seen: set[str] = set()
        for result in exact + results:
            if result.chunk.chunk_id in seen:
                continue
            seen.add(result.chunk.chunk_id)
            merged.append(result)
        merged = merged[: (top_k or self.top_k) + len(exact)]
        for rank, result in enumerate(merged):
            result.rank = rank

        expanded = self.retriever.expand_context(
            merged,
            max_tokens=self.max_context_tokens,
        )
        trace.append(
            {
                "step": "expand",
                "chunks": len(expanded),
                "token_estimate": sum(chunk.chunk.token_count for chunk in expanded),
            }
        )

        answer = self.answer_service.answer(question, expanded)
        answer.trace = trace + answer.trace
        return answer
