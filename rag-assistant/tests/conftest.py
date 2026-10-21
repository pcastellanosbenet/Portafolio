"""Shared test fixtures using deterministic, model-free components."""

from __future__ import annotations

import pytest
from qdrant_client import QdrantClient

from src.agent import KNXAgent
from src.answer import AnswerService
from src.embeddings import HashingEmbedder
from src.entities import EntityCatalog
from src.index import QdrantIndex
from src.llm import MockLLM
from src.models import Chunk, DocumentInfo, EntityRecord
from src.rerank import NoopReranker
from src.retrieve import ChunkStore, Retriever


def make_chunk(
    chunk_id: str,
    *,
    doc_id: str = "doc-dpt",
    title: str = "Datapoint Types",
    section: str = "3.7 Datapoint Types",
    text: str,
    content_type: str = "text",
    volume_number: str = "03",
    doc_number: str = "03_07_02",
    page: int = 10,
) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        title=title,
        volume="03 Volume 3 System Specifications",
        volume_number=volume_number,
        doc_number=doc_number,
        section=section,
        section_path=f"{title} > {section}",
        page_start=page,
        page_end=page,
        content_type=content_type,
        text=text,
        token_count=max(1, len(text) // 4),
        entities=[],
        source_sha="abc123",
    )


@pytest.fixture
def sample_chunks() -> list[Chunk]:
    return [
        make_chunk(
            "dpt::1",
            text=(
                "DPT 1.001 is a one-bit datapoint type used for switching. "
                "It is encoded as 0 or 1 and is often used for binary actuators."
            ),
            page=21,
        ),
        make_chunk(
            "dpt::2",
            text=(
                "DPT 14.046 represents magnetic flux density and uses the F32 "
                "format. The value is expressed in tesla."
            ),
            page=22,
        ),
        make_chunk(
            "res::1",
            doc_id="doc-resources",
            title="Resources",
            section="Properties",
            doc_number="03_05_01",
            text=(
                "PID_LOAD_STATE_CONTROL is a property identifier used to "
                "control the load state of a device."
            ),
            page=40,
        ),
        make_chunk(
            "cert::1",
            doc_id="doc-certification",
            title="Certification of Products",
            section="Procedure",
            doc_number="05",
            volume_number="05",
            text=(
                "The KNX certification procedure includes application, "
                "laboratory testing, and registration of the product."
            ),
            content_type="procedure",
            page=5,
        ),
    ]


@pytest.fixture
def hashing_embedder() -> HashingEmbedder:
    return HashingEmbedder(dimension=64)


@pytest.fixture
def memory_index(sample_chunks: list[Chunk], hashing_embedder: HashingEmbedder) -> QdrantIndex:
    client = QdrantClient(":memory:")
    index = QdrantIndex("test_collection", client=client)
    index.ensure_collection(hashing_embedder.dimension)
    vectors = hashing_embedder.embed_documents([chunk.text for chunk in sample_chunks])
    index.upsert_chunks(sample_chunks, vectors)
    return index


@pytest.fixture
def store(sample_chunks: list[Chunk]) -> ChunkStore:
    return ChunkStore(sample_chunks)


@pytest.fixture
def retriever(
    store: ChunkStore,
    memory_index: QdrantIndex,
    hashing_embedder: HashingEmbedder,
) -> Retriever:
    return Retriever(
        store,
        memory_index,
        hashing_embedder,
        NoopReranker(),
        candidate_k=10,
        top_k=5,
    )


@pytest.fixture
def catalog() -> EntityCatalog:
    return EntityCatalog(
        [
            EntityRecord(
                entity_id="dpt:1.001",
                kind="dpt",
                identifier="1.001",
                name="DPT_Switch",
                chunk_id="dpt::1",
                doc_id="doc-dpt",
                section="3.7 Datapoint Types",
                page=21,
                text="1.001 | B1 | DPT_Switch",
            )
        ]
    )


@pytest.fixture
def agent(retriever: Retriever, catalog: EntityCatalog) -> KNXAgent:
    llm = MockLLM(
        '{"answer": "DPT 1.001 is a one-bit switching datapoint type [S1].", '
        '"citations": ["S1"], "abstained": false}'
    )
    return KNXAgent(
        retriever,
        AnswerService(llm),
        catalog,
        top_k=3,
    )


@pytest.fixture
def sample_documents() -> list[DocumentInfo]:
    return [
        DocumentInfo(
            doc_id="doc-dpt",
            path="03_07_02 Datapoint Types v02.02.01 AS.pdf",
            title="Datapoint Types",
            volume="03 Volume 3 System Specifications",
            volume_number="03",
            doc_number="03_07_02",
            version="02.02.01",
            status="AS",
            sha256="abc123",
            pages=100,
        )
    ]
