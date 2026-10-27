"""Research sources: deterministic fixtures and live Wikipedia/arXiv clients."""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import unicodedata
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin, urlparse

import httpx

FIXTURES = Path(__file__).parent / "fixtures"
USER_AGENT = "mcp-gateway-research/0.1 (portfolio demo)"
ALLOWED_CONTENT_TYPES = {
    "application/json",
    "application/xml",
    "text/html",
    "text/plain",
    "text/xml",
}
MAX_REDIRECTS = 3
MAX_BYTES = 1_000_000
TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]+", re.IGNORECASE)
STOPWORDS = {
    "a",
    "al",
    "and",
    "de",
    "del",
    "el",
    "en",
    "for",
    "la",
    "las",
    "los",
    "of",
    "the",
    "to",
    "un",
    "una",
    "y",
}


def tokens(text: str) -> list[str]:
    """Tokenize text for deterministic lexical ranking."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [
        token
        for token in TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in STOPWORDS
    ]


def _rank(items: list[dict[str, Any]], query: str, limit: int) -> list[dict[str, Any]]:
    query_tokens = set(tokens(query))
    if not query_tokens:
        return []
    scored = []
    for item in items:
        haystack = " ".join(
            [
                str(item.get("title", "")),
                str(item.get("extract", item.get("summary", ""))),
                " ".join(item.get("tags", [])),
            ]
        )
        item_tokens = set(tokens(haystack))
        score = len(query_tokens & item_tokens) / max(1, len(query_tokens))
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], str(pair[1].get("title", ""))))
    return [
        {**item, "score": round(score, 4)}
        for score, item in scored[: max(1, min(limit, 10))]
    ]


class FixtureSource:
    """Deterministic local implementation used in tests and the demo."""

    def __init__(self, root: Path = FIXTURES) -> None:
        self.pages: list[dict[str, Any]] = json.loads(
            (root / "pages.json").read_text(encoding="utf-8")
        )
        self.papers: list[dict[str, Any]] = json.loads(
            (root / "arxiv.json").read_text(encoding="utf-8")
        )

    async def wikipedia_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _rank(self.pages, query, limit)

    async def wikipedia_get(self, title: str) -> dict[str, Any]:
        needle = title.strip().lower()
        for page in self.pages:
            if page["id"].lower() == needle or page["title"].lower() == needle:
                return page
        raise ValueError(f"unknown wikipedia page: {title}")

    async def arxiv_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        return _rank(self.papers, query, limit)

    async def arxiv_get(self, arxiv_id: str) -> dict[str, Any]:
        for paper in self.papers:
            if paper["id"] == arxiv_id:
                return paper
        raise ValueError(f"unknown arxiv paper: {arxiv_id}")


class LiveSource:
    """Live Wikipedia and arXiv clients. Requires network access."""

    async def _get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        async with httpx.AsyncClient(
            timeout=15, headers={"User-Agent": USER_AGENT}
        ) as client:
            response = await client.get(url, params=params)
            response.raise_for_status()
            return response

    async def wikipedia_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        response = await self._get(
            "https://en.wikipedia.org/w/api.php",
            {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "format": "json",
                "utf8": 1,
                "srlimit": max(1, min(limit, 10)),
            },
        )
        results = []
        for item in response.json().get("query", {}).get("search", []):
            snippet = re.sub(r"<[^>]+>", "", item.get("snippet", ""))
            results.append(
                {
                    "id": item["title"],
                    "title": item["title"],
                    "extract": snippet,
                    "url": f"https://en.wikipedia.org/wiki/{quote(item['title'])}",
                    "score": None,
                }
            )
        return results

    async def wikipedia_get(self, title: str) -> dict[str, Any]:
        response = await self._get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(title)}"
        )
        payload = response.json()
        return {
            "id": payload.get("title", title),
            "title": payload.get("title", title),
            "extract": payload.get("extract", ""),
            "url": payload.get("content_urls", {}).get("desktop", {}).get("page", ""),
        }

    async def arxiv_search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        response = await self._get(
            "https://export.arxiv.org/api/query",
            {
                "search_query": f"all:{query}",
                "start": 0,
                "max_results": max(1, min(limit, 10)),
            },
        )
        return self._parse_arxiv(response.text)

    async def arxiv_get(self, arxiv_id: str) -> dict[str, Any]:
        response = await self._get(
            "https://export.arxiv.org/api/query",
            {"id_list": arxiv_id, "max_results": 1},
        )
        papers = self._parse_arxiv(response.text)
        if not papers:
            raise ValueError(f"unknown arxiv paper: {arxiv_id}")
        return papers[0]

    @staticmethod
    def _parse_arxiv(xml_text: str) -> list[dict[str, Any]]:
        import xml.etree.ElementTree as ET

        namespace = {"atom": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml_text)
        papers = []
        for entry in root.findall("atom:entry", namespace):
            papers.append(
                {
                    "id": (entry.findtext("atom:id", default="", namespaces=namespace) or "")
                    .rsplit("/", 1)[-1],
                    "title": " ".join(
                        (
                            entry.findtext("atom:title", default="", namespaces=namespace)
                            or ""
                        ).split()
                    ),
                    "summary": " ".join(
                        (
                            entry.findtext("atom:summary", default="", namespaces=namespace)
                            or ""
                        ).split()
                    ),
                    "published": entry.findtext(
                        "atom:published", default="", namespaces=namespace
                    ),
                    "url": entry.findtext(
                        "atom:id", default="", namespaces=namespace
                    ),
                    "authors": [
                        author.findtext("atom:name", default="", namespaces=namespace)
                        for author in entry.findall("atom:author", namespace)
                    ],
                }
            )
        return papers


def validate_url(url: str) -> str:
    """Reject non-HTTP schemes and hostnames that resolve to non-public addresses."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("only http and https URLs are allowed")
    hostname = parsed.hostname
    if not hostname:
        raise ValueError("URL must include a hostname")
    lowered = hostname.lower()
    if lowered in {"localhost", "localhost.localdomain"} or lowered.endswith(".local"):
        raise ValueError("local hostnames are not allowed")
    try:
        addresses = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        raise ValueError(f"cannot resolve hostname: {hostname}") from exc
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if not ip.is_global:
            raise ValueError(f"URL resolves to a non-public address: {ip}")
    return url


async def fetch_url(url: str, max_chars: int = 4000) -> dict[str, Any]:
    """Fetch a public URL with SSRF checks, redirect validation and a byte cap."""
    current = validate_url(url)
    async with httpx.AsyncClient(
        timeout=15,
        follow_redirects=False,
        headers={"User-Agent": USER_AGENT},
    ) as client:
        for _ in range(MAX_REDIRECTS + 1):
            response = await client.get(current)
            if response.is_redirect:
                location = response.headers.get("location")
                if not location:
                    raise ValueError("redirect without Location header")
                current = validate_url(urljoin(current, location))
                continue
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";")[0].strip()
            if content_type and content_type not in ALLOWED_CONTENT_TYPES:
                raise ValueError(f"unsupported content type: {content_type}")
            chunks: list[bytes] = []
            total = 0
            async for chunk in response.aiter_bytes():
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError("response exceeds the 1 MB limit")
                chunks.append(chunk)
            text = b"".join(chunks).decode("utf-8", errors="replace")
            return {
                "url": current,
                "status_code": response.status_code,
                "content_type": content_type,
                "text": text[: max(1, max_chars)],
                "truncated": len(text) > max_chars,
            }
        raise ValueError("too many redirects")


class ResearchService:
    """Select the fixture or live source once per server process."""

    def __init__(self, mode: str = "fixtures") -> None:
        if mode not in {"fixtures", "live"}:
            raise ValueError(f"unknown research mode: {mode}")
        self.mode = mode
        self.source: FixtureSource | LiveSource = (
            FixtureSource() if mode == "fixtures" else LiveSource()
        )

    async def wikipedia_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "results": await self.source.wikipedia_search(query, limit),
        }

    async def wikipedia_get(self, title: str) -> dict[str, Any]:
        return {"mode": self.mode, **(await self.source.wikipedia_get(title))}

    async def arxiv_search(self, query: str, limit: int = 5) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "results": await self.source.arxiv_search(query, limit),
        }

    async def arxiv_get(self, arxiv_id: str) -> dict[str, Any]:
        return {"mode": self.mode, **(await self.source.arxiv_get(arxiv_id))}
