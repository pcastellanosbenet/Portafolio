from src.models import SearchFilters
from src.retrieve import Retriever


def test_hybrid_retrieval_finds_dpt_chunk(retriever: Retriever) -> None:
    results = retriever.search("What is DPT 1.001?", top_k=3)
    assert results
    assert results[0].chunk.chunk_id == "dpt::1"
    assert results[0].score > 0


def test_metadata_filter_restricts_results(retriever: Retriever) -> None:
    results = retriever.search(
        "load state property",
        filters=SearchFilters(doc_number="03_05_01"),
        top_k=3,
    )
    assert results
    assert all(result.chunk.doc_number == "03_05_01" for result in results)


def test_empty_store_is_safe(hashing_embedder) -> None:
    from qdrant_client import QdrantClient

    from src.index import QdrantIndex
    from src.rerank import NoopReranker
    from src.retrieve import ChunkStore

    empty_index = QdrantIndex("empty", client=QdrantClient(":memory:"))
    empty_index.ensure_collection(hashing_embedder.dimension)
    empty = ChunkStore([])
    retrieval = Retriever(empty, empty_index, hashing_embedder, NoopReranker(), top_k=3)
    assert retrieval.search("anything", top_k=3) == []
