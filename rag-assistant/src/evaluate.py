"""Retrieval evaluation over a human-curated question set."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.config import Settings
from src.embeddings import get_embedder
from src.entities import build_query_plan
from src.index import QdrantIndex
from src.models import RetrievedChunk
from src.rerank import get_reranker
from src.retrieve import ChunkStore, Retriever


@dataclass
class EvalQuestion:
    id: str
    question: str
    relevant_doc_ids: list[str]
    language: str = "en"
    type: str = "general"
    relevant_pages: list[int] = field(default_factory=list)
    reference_answer: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EvalQuestion:
        return cls(
            id=str(data["id"]),
            question=str(data["question"]),
            relevant_doc_ids=[str(value) for value in data.get("relevant_doc_ids", [])],
            language=str(data.get("language", "en")),
            type=str(data.get("type", "general")),
            relevant_pages=[int(value) for value in data.get("relevant_pages", [])],
            reference_answer=str(data.get("reference_answer", "")),
        )


def load_questions(path: Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                questions.append(EvalQuestion.from_dict(json.loads(line)))
    return questions


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _ndcg(retrieved: list[str], relevant: set[str], k: int) -> float:
    dcg = 0.0
    for rank, doc_id in enumerate(retrieved[:k], start=1):
        if doc_id in relevant:
            dcg += 1.0 / math.log2(rank + 1)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def _page_hit(results: list[RetrievedChunk], pages: list[int], k: int) -> bool:
    if not pages:
        return False
    for result in results[:k]:
        if any(
            result.chunk.page_start <= page <= result.chunk.page_end
            for page in pages
        ):
            return True
    return False


def evaluate_question(
    retriever: Retriever,
    question: EvalQuestion,
    *,
    k: int,
) -> dict[str, Any]:
    plan = build_query_plan(question.question)
    results = retriever.search(plan.expanded, top_k=k)
    retrieved_docs = _dedupe([result.chunk.doc_id for result in results])
    relevant = set(question.relevant_doc_ids)
    hits = [doc_id for doc_id in retrieved_docs if doc_id in relevant]
    first_relevant = next(
        (rank for rank, doc_id in enumerate(retrieved_docs, start=1) if doc_id in relevant),
        None,
    )
    row: dict[str, Any] = {
        "id": question.id,
        "question": question.question,
        "language": question.language,
        "type": question.type,
        "retrieved_doc_ids": retrieved_docs,
        "relevant_doc_ids": sorted(relevant),
        "recall_at_k": len(hits) / len(relevant) if relevant else 0.0,
        "hit_at_k": float(bool(hits)),
        "mrr": 1.0 / first_relevant if first_relevant else 0.0,
        "ndcg_at_k": _ndcg(retrieved_docs, relevant, k),
        "top_chunks": [
            {
                "chunk_id": result.chunk.chunk_id,
                "doc_id": result.chunk.doc_id,
                "section": result.chunk.section_path,
                "pages": [result.chunk.page_start, result.chunk.page_end],
                "score": round(result.score, 6),
            }
            for result in results[:k]
        ],
    }
    if question.relevant_pages:
        row["page_hit_at_k"] = float(
            _page_hit(results, question.relevant_pages, k)
        )
    return row


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, float]:
    if not rows:
        return {}
    keys = ["recall_at_k", "hit_at_k", "mrr", "ndcg_at_k", "page_hit_at_k"]
    result: dict[str, float] = {}
    for key in keys:
        values = [float(row[key]) for row in rows if key in row]
        if values:
            result[key] = round(sum(values) / len(values), 4)
    return result


def evaluate(
    retriever: Retriever,
    questions: list[EvalQuestion],
    *,
    k: int = 10,
) -> dict[str, Any]:
    rows = [evaluate_question(retriever, question, k=k) for question in questions]
    by_type: dict[str, list[dict[str, Any]]] = {}
    by_language: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_type.setdefault(row["type"], []).append(row)
        by_language.setdefault(row["language"], []).append(row)
    return {
        "k": k,
        "questions": len(rows),
        "overall": _aggregate(rows),
        "by_type": {key: _aggregate(value) for key, value in sorted(by_type.items())},
        "by_language": {
            key: _aggregate(value) for key, value in sorted(by_language.items())
        },
        "details": rows,
    }


def _build_retriever(settings: Settings) -> Retriever:
    store = ChunkStore.load(settings.chunks_path)
    if not store.chunks:
        raise SystemExit(
            f"No hay chunks en {settings.chunks_path}. Ejecuta src.ingest primero."
        )
    embedder = get_embedder(settings)
    index = QdrantIndex(
        settings.collection_name,
        url=settings.qdrant_url,
        path=str(settings.effective_qdrant_path) if not settings.qdrant_url else None,
        timeout=settings.qdrant_timeout,
    )
    return Retriever(
        store,
        index,
        embedder,
        get_reranker(settings),
        rrf_k=settings.rrf_k,
        candidate_k=settings.candidate_k,
        rerank_k=settings.rerank_k,
        top_k=settings.top_k,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa la recuperación del RAG KNX.")
    parser.add_argument("--questions", type=Path, default=Path("eval/questions.jsonl"))
    parser.add_argument("--artifacts", type=Path)
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--output", type=Path, default=Path("eval/results/retrieval.json"))
    parser.add_argument("--no-reranker", action="store_true")
    parser.add_argument("--embedding-backend", choices=["transformers", "hashing"])
    args = parser.parse_args()

    updates: dict[str, Any] = {}
    if args.artifacts:
        updates["artifacts_dir"] = args.artifacts
    if args.corpus:
        updates["corpus_dir"] = args.corpus
    if args.no_reranker:
        updates["use_reranker"] = False
    if args.embedding_backend:
        updates["embedding_backend"] = args.embedding_backend
    settings = Settings(**updates)
    questions = load_questions(args.questions)
    retriever = _build_retriever(settings)
    report = evaluate(retriever, questions, k=args.top_k)
    report["config"] = {
        "embedding_model": settings.embedding_model,
        "reranker": None if args.no_reranker else settings.reranker_model,
        "artifacts_dir": str(settings.artifacts_dir),
        "qdrant_path": (
            None if settings.qdrant_url else str(settings.effective_qdrant_path)
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report["overall"], indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
