"""arXiv Atom API backend."""

from __future__ import annotations

import time
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.base import SearchError, SearchResult
from src.tools.urls import dedupe_results, normalize_query, query_cache_key, source_id_for_url

ARXIV_URL = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"


class ArxivSearchBackend:
    name = "arxiv"

    def __init__(
        self,
        *,
        cache: SQLiteCache,
        settings: Settings,
        client: httpx.Client | None = None,
    ) -> None:
        self.cache = cache
        self.settings = settings
        self._client = client or httpx.Client(timeout=settings.http_timeout_s)

    def search(self, query: str, *, max_results: int = 5) -> list[SearchResult]:
        query = normalize_query(query)
        if not query:
            raise SearchError("arXiv query is empty.")
        limit = max(1, min(max_results, 10))
        cache_key = self.cache.make_key(
            "search:arxiv",
            {"query": query_cache_key(query), "max_results": limit},
        )
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return [
                SearchResult.model_validate(item).model_copy(
                    update={"metadata": {**item.get("metadata", {}), "cached": "1"}}
                )
                for item in cached
            ]

        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        response = self._get(params)
        results = self._parse(response.text)
        results = dedupe_results(results)
        self.cache.set_json(
            cache_key,
            [result.model_dump(mode="json") for result in results],
        )
        return results

    def _get(self, params: dict[str, object]) -> httpx.Response:
        attempts = self.settings.search_max_retries + 1
        last_error = "unknown error"
        for attempt in range(attempts):
            try:
                response = self._client.get(ARXIV_URL, params=params)
            except httpx.HTTPError as exc:
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt + 1 < attempts:
                    time.sleep(min(2**attempt, 5))
                    continue
                break
            if response.status_code in {429, 500, 502, 503, 504} and attempt + 1 < attempts:
                last_error = f"HTTP {response.status_code}"
                time.sleep(min(2**attempt, 5))
                continue
            if response.status_code >= 400:
                raise SearchError(f"arXiv returned HTTP {response.status_code}.")
            return response
        raise SearchError(f"arXiv request failed after {attempts} attempt(s): {last_error}.")

    @staticmethod
    def _parse(xml_text: str) -> list[SearchResult]:
        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            raise SearchError("arXiv returned invalid XML.") from exc
        results: list[SearchResult] = []
        for entry in root.findall(f"{ATOM}entry"):
            title = " ".join((entry.findtext(f"{ATOM}title") or "").split())
            summary = " ".join((entry.findtext(f"{ATOM}summary") or "").split())
            raw_id = (entry.findtext(f"{ATOM}id") or "").strip()
            url = raw_id
            for link in entry.findall(f"{ATOM}link"):
                if link.get("rel") == "alternate" and link.get("href"):
                    url = link.get("href", "")
                    break
            url = url.replace("http://arxiv.org/", "https://arxiv.org/")
            if not url:
                continue
            authors = [
                " ".join((author.findtext(f"{ATOM}name") or "").split())
                for author in entry.findall(f"{ATOM}author")
            ]
            published = entry.findtext(f"{ATOM}published")
            published_at: datetime | None = None
            if published:
                try:
                    published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                except ValueError:
                    published_at = None
            results.append(
                SearchResult(
                    source_id=source_id_for_url(url),
                    title=title or url,
                    url=url,
                    snippet=summary[:1200],
                    kind="arxiv",
                    backend="arxiv",
                    published_at=published_at,
                    metadata={
                        "authors": "; ".join(author for author in authors if author),
                        "published": published or "",
                        "backend": "arxiv",
                    },
                )
            )
        return results
