"""Pydantic request/response models for the local API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.models import AgentAnswer, DocumentInfo, RetrievedChunk, SearchFilters
from src.text import truncate


class FilterRequest(BaseModel):
    volume_number: str | None = None
    doc_id: str | None = None
    doc_number: str | None = None
    content_type: str | None = None
    entity: str | None = None

    def to_search_filters(self) -> SearchFilters:
        return SearchFilters(
            volume_number=self.volume_number,
            doc_id=self.doc_id,
            doc_number=self.doc_number,
            content_type=self.content_type,
            entity=self.entity,
        )


class QueryRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    filters: FilterRequest = Field(default_factory=FilterRequest)
    session_id: str | None = None


class CitationModel(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section: str
    page_start: int
    page_end: int
    quote: str


class SourceModel(BaseModel):
    chunk_id: str
    doc_id: str
    title: str
    section: str
    page_start: int
    page_end: int
    content_type: str
    score: float
    text: str


class QueryResponse(BaseModel):
    answer: str
    citations: list[CitationModel]
    abstained: bool
    sources: list[SourceModel]
    trace: list[dict[str, Any]]
    used_llm: bool

    @classmethod
    def from_agent_answer(cls, answer: AgentAnswer) -> QueryResponse:
        return cls(
            answer=answer.answer,
            citations=[CitationModel(**citation.to_dict()) for citation in answer.citations],
            abstained=answer.abstained,
            sources=[_source_model(source) for source in answer.sources],
            trace=answer.trace,
            used_llm=answer.used_llm,
        )


def _source_model(source: RetrievedChunk) -> SourceModel:
    chunk = source.chunk
    return SourceModel(
        chunk_id=chunk.chunk_id,
        doc_id=chunk.doc_id,
        title=chunk.title,
        section=chunk.section_path,
        page_start=chunk.page_start,
        page_end=chunk.page_end,
        content_type=chunk.content_type,
        score=round(float(source.score), 6),
        text=truncate(chunk.text, 600),
    )


class DocumentSummary(BaseModel):
    doc_id: str
    title: str
    volume: str
    volume_number: str
    doc_number: str
    version: str
    status: str
    pages: int
    path: str

    @classmethod
    def from_document(cls, document: DocumentInfo) -> DocumentSummary:
        return cls(
            doc_id=document.doc_id,
            title=document.title,
            volume=document.volume,
            volume_number=document.volume_number,
            doc_number=document.doc_number,
            version=document.version,
            status=document.status,
            pages=document.pages,
            path=document.path,
        )


class HealthResponse(BaseModel):
    status: str
    chunks: int
    collection: str
    embedding_model: str
    reranker_model: str | None
    llm_model: str
    ollama_available: bool
    artifacts_ready: bool


class ReloadResponse(BaseModel):
    status: str
    chunks: int


class ErrorResponse(BaseModel):
    detail: str


class TraceModel(BaseModel):
    model_config = ConfigDict(extra="allow")
