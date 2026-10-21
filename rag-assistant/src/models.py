"""Shared data models for the KNX RAG assistant."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DocumentInfo:
    """Metadata for one source PDF."""

    doc_id: str
    path: str
    title: str
    volume: str
    volume_number: str
    doc_number: str
    version: str
    status: str
    sha256: str
    pages: int
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DocumentInfo:
        return cls(**data)


@dataclass
class Chunk:
    """A retrievable unit of text with provenance metadata."""

    chunk_id: str
    doc_id: str
    title: str
    volume: str
    volume_number: str
    doc_number: str
    section: str
    section_path: str
    page_start: int
    page_end: int
    content_type: str
    text: str
    token_count: int
    entities: list[str] = field(default_factory=list)
    source_sha: str = ""
    language: str = "en"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Chunk:
        return cls(**data)


@dataclass(frozen=True)
class EntityRecord:
    """A structured KNX identifier extracted from a table or document."""

    entity_id: str
    kind: str
    identifier: str
    name: str
    chunk_id: str
    doc_id: str
    section: str
    page: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EntityRecord:
        return cls(**data)


@dataclass(frozen=True)
class SearchFilters:
    """Optional metadata filters applied to both retrievers."""

    volume_number: str | None = None
    doc_id: str | None = None
    doc_number: str | None = None
    content_type: str | None = None
    entity: str | None = None

    def is_empty(self) -> bool:
        return not any(
            (
                self.volume_number,
                self.doc_id,
                self.doc_number,
                self.content_type,
                self.entity,
            )
        )


@dataclass
class RetrievedChunk:
    """A chunk returned by retrieval, with component scores."""

    chunk: Chunk
    score: float
    dense_score: float | None = None
    bm25_score: float | None = None
    rerank_score: float | None = None
    rank: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


@dataclass
class Citation:
    """A source attached to a generated answer."""

    chunk_id: str
    doc_id: str
    title: str
    section: str
    page_start: int
    page_end: int
    quote: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAnswer:
    """Final answer returned by the agent."""

    answer: str
    citations: list[Citation]
    abstained: bool
    sources: list[RetrievedChunk] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    used_llm: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "answer": self.answer,
            "citations": [citation.to_dict() for citation in self.citations],
            "abstained": self.abstained,
            "sources": [source.to_dict() for source in self.sources],
            "trace": self.trace,
            "used_llm": self.used_llm,
        }
