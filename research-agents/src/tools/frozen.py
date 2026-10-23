"""Frozen search and page-fetch backends for reproducible evaluations.

The evaluation corpus is a JSON document with a list of ``documents``. Each
document stores the excerpt used as evidence, its URL, license and SHA-256.
Search is deterministic: it ranks documents with a small lexical scorer and
returns sentence windows, so every system evaluated with the same corpus sees
the same evidence. The legacy exact-query format (``queries``) is still
supported for small fixtures.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path
from typing import Any

from src.tools.base import FetchedPage, FetchError, SearchError, SearchResult
from src.tools.urls import (
    canonicalize_url,
    dedupe_results,
    normalize_query,
    query_cache_key,
    source_id_for_url,
)

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")
_STOPWORDS = {
    "a",
    "al",
    "algo",
    "an",
    "and",
    "are",
    "as",
    "como",
    "con",
    "de",
    "del",
    "does",
    "el",
    "en",
    "es",
    "esta",
    "este",
    "for",
    "from",
    "ha",
    "how",
    "in",
    "is",
    "la",
    "las",
    "lo",
    "los",
    "más",
    "no",
    "o",
    "of",
    "on",
    "or",
    "para",
    "pero",
    "por",
    "que",
    "qué",
    "se",
    "sin",
    "son",
    "su",
    "sus",
    "that",
    "the",
    "their",
    "to",
    "un",
    "una",
    "y",
    "you",
}


def _normalize_text(text: str) -> str:
    decomposed = unicodedata.normalize("NFD", text.casefold())
    return "".join(char for char in decomposed if unicodedata.category(char) != "Mn")


def _tokens(text: str) -> list[str]:
    normalized = _normalize_text(text)
    return [
        token
        for token in _TOKEN_RE.findall(normalized)
        if len(token) >= 3 and token not in _STOPWORDS
    ]


def _window(text: str, query_tokens: set[str], *, limit: int = 700) -> str:
    """Return the most query-relevant sentence window from a document."""
    sentences = [sentence.strip() for sentence in _SENTENCE_RE.split(text) if sentence.strip()]
    if not sentences:
        return text[:limit]
    scored: list[tuple[int, int, str]] = []
    for index, sentence in enumerate(sentences):
        tokens = set(_tokens(sentence))
        overlap = len(tokens & query_tokens)
        scored.append((overlap, -index, sentence))
    scored.sort(reverse=True)
    chosen = [sentence for overlap, _, sentence in scored[:2] if overlap > 0]
    if not chosen:
        chosen = sentences[:2]
    result = " ".join(chosen)
    if len(result) > limit:
        result = result[: limit - 1].rstrip() + "…"
    return result


class FrozenSearchBackend:
    """Read search results from a JSON corpus.

    Expected shape::

        {
          "documents": [
            {"title": "...", "url": "...", "content": "...", ...}
          ],
          "queries": {"question": [{"title": "...", "url": "...", "snippet": "..."}]}
        }

    ``queries`` is optional and kept for backwards compatibility. When a query
    is present there, its rows take precedence over lexical retrieval.
    """

    name = "frozen"

    def __init__(self, path: Path) -> None:
        self.path = path
        if not path.is_file():
            raise SearchError(f"Frozen corpus not found: {path}")
        try:
            self._data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SearchError(f"Could not read frozen corpus {path}: {exc}") from exc
        if not isinstance(self._data, dict):
            raise SearchError("Frozen corpus must be a JSON object.")
        queries = self._data.get("queries", {})
        if not isinstance(queries, dict):
            raise SearchError("Frozen corpus 'queries' must be an object.")
        documents = self._data.get("documents", [])
        if not isinstance(documents, list):
            raise SearchError("Frozen corpus 'documents' must be a list.")
        self._queries: dict[str, list[dict[str, Any]]] = queries
        self._documents = [row for row in documents if isinstance(row, dict)]
        self._by_url: dict[str, dict[str, Any]] = {}
        for document in self._documents:
            url = str(document.get("url") or "").strip()
            if not url:
                continue
            try:
                canonical = canonicalize_url(url)
            except Exception as exc:  # noqa: BLE001 - invalid corpus rows are skipped
                raise SearchError(f"Invalid URL in frozen corpus: {url!r}") from exc
            self._by_url[canonical] = document

    @property
    def documents(self) -> list[dict[str, Any]]:
        return list(self._documents)

    def get_document(self, url: str) -> dict[str, Any] | None:
        try:
            return self._by_url.get(canonicalize_url(url))
        except Exception:  # noqa: BLE001 - an invalid URL is simply not in the corpus
            return None

    def _legacy_results(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[SearchResult] | None:
        key = query_cache_key(normalize_query(query))
        rows = self._queries.get(key)
        if rows is None:
            rows = self._queries.get(normalize_query(query))
        if rows is None:
            return None
        results = []
        for row in rows[: max(1, min(max_results, 10))]:
            url = str(row.get("url", "")).strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=str(row.get("title") or url).strip(),
                    url=url,
                    snippet=str(row.get("snippet") or "").strip(),
                    kind=str(row.get("kind") or "web"),  # type: ignore[arg-type]
                    backend=self.name,
                    metadata={"backend": self.name},
                )
            )
        return dedupe_results(results)

    def _score_document(
        self,
        query: str,
        query_tokens: set[str],
        document: dict[str, Any],
    ) -> float:
        title = str(document.get("title") or "")
        content = str(document.get("content") or "")
        aliases = " ".join(str(alias) for alias in document.get("aliases", []) or [])
        title_tokens = set(_tokens(f"{title} {aliases}"))
        content_tokens = Counter(_tokens(content))
        if not query_tokens:
            return 0.0
        score = 0.0
        for token in query_tokens:
            if token in title_tokens:
                score += 5.0
            frequency = content_tokens.get(token, 0)
            if frequency:
                score += 1.0 + math.log1p(frequency)
        normalized_query = _normalize_text(normalize_query(query))
        normalized_title = _normalize_text(title)
        if normalized_query and normalized_query in normalized_title:
            score += 8.0
        for alias in document.get("aliases", []) or []:
            normalized_alias = _normalize_text(str(alias))
            if len(normalized_alias) >= 3 and normalized_alias in normalized_query:
                score += 12.0
        if normalized_query and normalized_query in _normalize_text(content):
            score += 5.0
        return score

    def _document_results(
        self,
        query: str,
        *,
        max_results: int,
    ) -> list[SearchResult]:
        query_tokens = set(_tokens(query))
        if not query_tokens:
            return []
        scored: list[tuple[float, dict[str, Any]]] = []
        for document in self._documents:
            score = self._score_document(query, query_tokens, document)
            if score > 0:
                scored.append((score, document))
        scored.sort(key=lambda item: item[0], reverse=True)
        results: list[SearchResult] = []
        for score, document in scored[: max(1, min(max_results, 10))]:
            url = str(document.get("url") or "").strip()
            content = str(document.get("content") or "")
            title = str(document.get("title") or url).strip()
            if not url:
                continue
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=title,
                    url=url,
                    snippet=_window(content, query_tokens),
                    kind=str(document.get("kind") or "web"),  # type: ignore[arg-type]
                    backend=self.name,
                    score=round(score, 4),
                    metadata={
                        "backend": self.name,
                        "doc_id": str(document.get("doc_id") or ""),
                        "license": str(document.get("license") or ""),
                        "attribution": str(document.get("attribution") or ""),
                        "retrieved_at": str(document.get("retrieved_at") or ""),
                        "language": str(document.get("language") or ""),
                    },
                )
            )
        return dedupe_results(results)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        legacy = self._legacy_results(query, max_results=max_results)
        if legacy is not None:
            return legacy
        return self._document_results(query, max_results=max_results)


class FrozenPageFetcher:
    """Return a corpus document for ``fetch_page`` calls in offline runs."""

    name = "frozen"

    def __init__(self, backend: FrozenSearchBackend) -> None:
        self.backend = backend

    def fetch(self, url: str) -> FetchedPage:
        document = self.backend.get_document(url)
        if document is None:
            raise FetchError(f"URL is not in the frozen corpus: {url}")
        canonical = canonicalize_url(str(document["url"]))
        content = str(document.get("content") or "")
        return FetchedPage(
            source_id=source_id_for_url(canonical),
            url=canonical,
            final_url=canonical,
            title=str(document.get("title") or canonical),
            text=content,
            status_code=200,
            content_type="text/plain; charset=utf-8",
            truncated=False,
            cached=True,
        )
