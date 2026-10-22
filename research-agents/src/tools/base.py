"""Shared types and errors for search and page-fetching tools."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from src.models import Source, SourceKind


class ToolError(RuntimeError):
    """Base error for recoverable tool failures."""


class SearchError(ToolError):
    """Raised when a search backend cannot return results."""


class SearchBudgetExceeded(SearchError):
    """Raised when the monthly search budget is exhausted."""


class FetchError(ToolError):
    """Raised when a page cannot be fetched or extracted."""


class UnsafeURLError(FetchError):
    """Raised when a URL is not safe to fetch (SSRF or unsupported scheme)."""


class SearchResult(BaseModel):
    """One normalized result returned by any search backend."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    title: str
    url: str
    snippet: str = ""
    kind: SourceKind = "web"
    backend: str = ""
    score: float | None = None
    published_at: datetime | None = None
    metadata: dict[str, str] = Field(default_factory=dict)

    def to_source(self) -> Source:
        return Source(
            source_id=self.source_id,
            url=self.url,
            title=self.title,
            kind=self.kind,
            snippet=self.snippet,
            metadata=dict(self.metadata),
        )


class FetchedPage(BaseModel):
    """Extracted text for one page."""

    model_config = ConfigDict(extra="forbid")

    source_id: str
    url: str
    final_url: str
    title: str
    text: str
    status_code: int
    content_type: str
    truncated: bool = False
    cached: bool = False


class SearchBackend(Protocol):
    name: str

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]: ...


class PageFetcher(Protocol):
    def fetch(self, url: str) -> FetchedPage: ...
