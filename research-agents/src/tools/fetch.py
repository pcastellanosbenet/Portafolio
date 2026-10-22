"""HTTP page fetcher with SSRF protection and readable-text extraction."""

from __future__ import annotations

import re
from urllib.parse import urljoin

import httpx
import trafilatura

from src.cache import SQLiteCache
from src.config import Settings
from src.tools.base import FetchedPage, FetchError
from src.tools.urls import (
    Resolver,
    canonicalize_url,
    source_id_for_url,
    validate_public_url,
)

_ALLOWED_CONTENT_TYPES = {
    "text/html",
    "application/xhtml+xml",
    "text/plain",
}
_TAG_RE = re.compile(r"<[^>]+>")
_MAX_REDIRECTS = 3


class HttpPageFetcher:
    """Fetch a public page, validate redirects and extract its main text."""

    def __init__(
        self,
        *,
        cache: SQLiteCache,
        settings: Settings,
        client: httpx.Client | None = None,
        resolver: Resolver | None = None,
    ) -> None:
        self.cache = cache
        self.settings = settings
        self._resolver = resolver
        self._client = client or httpx.Client(
            timeout=settings.http_timeout_s,
            follow_redirects=False,
            headers={
                "User-Agent": "multi-agent-research/0.1 (portfolio project)",
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.1",
            },
        )

    def fetch(self, url: str) -> FetchedPage:
        canonical = canonicalize_url(url)
        cache_key = self.cache.make_key("page", {"url": canonical})
        cached = self.cache.get_json(cache_key)
        if cached is not None:
            return FetchedPage.model_validate(cached).model_copy(update={"cached": True})

        current = canonical
        for redirect in range(_MAX_REDIRECTS + 1):
            validate_public_url(current, resolver=self._resolver)
            try:
                response = self._client.get(current)
            except httpx.HTTPError as exc:
                raise FetchError(f"Could not fetch {current}: {type(exc).__name__}.") from exc

            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise FetchError(f"Redirect from {current} has no Location header.")
                if redirect >= _MAX_REDIRECTS:
                    raise FetchError(f"Too many redirects while fetching {url}.")
                current = canonicalize_url(urljoin(current, location))
                continue

            if response.status_code >= 400:
                raise FetchError(f"Fetching {current} returned HTTP {response.status_code}.")

            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            if content_type not in _ALLOWED_CONTENT_TYPES:
                raise FetchError(f"Unsupported content type {content_type!r} at {current}.")

            raw = response.content
            truncated = len(raw) > self.settings.http_max_bytes
            raw = raw[: self.settings.http_max_bytes]
            html_text = raw.decode(response.encoding or "utf-8", errors="replace")
            title, text = _extract_text(html_text, content_type, current)
            if not text:
                raise FetchError(f"No readable text found at {current}.")
            if len(text) > self.settings.fetch_max_chars:
                text = text[: self.settings.fetch_max_chars]
                truncated = True
            page = FetchedPage(
                source_id=source_id_for_url(current),
                url=canonical,
                final_url=canonicalize_url(current),
                title=title,
                text=text,
                status_code=response.status_code,
                content_type=content_type,
                truncated=truncated,
                cached=False,
            )
            self.cache.set_json(cache_key, page.model_dump(mode="json"))
            return page
        raise FetchError(f"Too many redirects while fetching {url}.")


def _extract_text(html_text: str, content_type: str, url: str) -> tuple[str, str]:
    if content_type == "text/plain":
        return url, " ".join(html_text.split())

    title = url
    try:
        metadata = trafilatura.extract_metadata(html_text)
        if metadata and metadata.title:
            title = metadata.title.strip()
    except Exception:  # noqa: BLE001 - metadata is best effort
        pass

    try:
        extracted = trafilatura.extract(
            html_text,
            include_comments=False,
            include_tables=False,
            favor_recall=True,
        )
    except Exception:  # noqa: BLE001 - fall back to a simple tag stripper
        extracted = None
    if extracted:
        return title, extracted.strip()

    fallback = " ".join(_TAG_RE.sub(" ", html_text).split())
    return title, fallback
