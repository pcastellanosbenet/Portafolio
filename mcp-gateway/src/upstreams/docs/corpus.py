"""Load and search the docs-mcp corpus."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rank_bm25 import BM25Okapi

TOKEN_RE = re.compile(r"[a-z0-9áéíóúüñ]+", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+)$")
STOPWORDS = {
    "a",
    "al",
    "algo",
    "como",
    "con",
    "de",
    "del",
    "el",
    "en",
    "es",
    "esta",
    "este",
    "for",
    "la",
    "las",
    "lo",
    "los",
    "más",
    "no",
    "o",
    "para",
    "pero",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "the",
    "to",
    "un",
    "una",
    "y",
    "ya",
}


def tokenize(text: str) -> list[str]:
    """Tokenize text, removing accents and common stopwords."""
    normalized = unicodedata.normalize("NFKD", text.lower())
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return [
        token
        for token in TOKEN_RE.findall(normalized)
        if len(token) > 1 and token not in STOPWORDS
    ]


@dataclass(frozen=True)
class Document:
    """One corpus document."""

    id: str
    title: str
    tags: list[str]
    path: str
    content: str
    word_count: int
    sha256: str


class DocsCorpus:
    """BM25 index over the bundled technical corpus."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(__file__).parent / "corpus"
        manifest = json.loads((self.root / "manifest.json").read_text(encoding="utf-8"))
        self.documents = [self._load(entry) for entry in manifest]
        self._by_id = {document.id: document for document in self.documents}
        self._tokens = [
            tokenize(f"{document.title} {' '.join(document.tags)} {document.content}")
            for document in self.documents
        ]
        self._bm25 = BM25Okapi(self._tokens)

    def _load(self, entry: dict[str, Any]) -> Document:
        path = self.root / entry["path"]
        content = path.read_text(encoding="utf-8")
        return Document(
            id=entry["id"],
            title=entry["title"],
            tags=list(entry["tags"]),
            path=entry["path"],
            content=content,
            word_count=len(content.split()),
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return the best documents for a query, with a paragraph snippet."""
        tokens = tokenize(query)
        if not tokens:
            return []
        scores = self._bm25.get_scores(tokens)
        ranked = sorted(
            zip(self.documents, scores, strict=True),
            key=lambda item: (-item[1], item[0].id),
        )
        results: list[dict[str, Any]] = []
        for document, score in ranked[: max(1, min(limit, 10))]:
            if score <= 0:
                continue
            results.append(
                {
                    "doc_id": document.id,
                    "title": document.title,
                    "tags": document.tags,
                    "snippet": self._snippet(document.content, tokens),
                    "score": round(float(score), 4),
                }
            )
        return results

    def _snippet(self, content: str, tokens: list[str]) -> str:
        paragraphs = [paragraph.strip() for paragraph in content.split("\n\n")]
        tokenset = set(tokens)
        best = max(
            paragraphs,
            key=lambda paragraph: len(tokenset & set(tokenize(paragraph))),
            default=content,
        )
        best = " ".join(best.split())
        return best[:320] + ("…" if len(best) > 320 else "")

    def read(self, doc_id: str) -> Document:
        """Return one document or raise a clear KeyError."""
        try:
            return self._by_id[doc_id]
        except KeyError as exc:
            raise KeyError(f"unknown document: {doc_id}") from exc

    def list_documents(self) -> list[dict[str, Any]]:
        """Return compact metadata for every document."""
        return [
            {
                "doc_id": document.id,
                "title": document.title,
                "tags": document.tags,
                "words": document.word_count,
            }
            for document in self.documents
        ]

    def outline(self, doc_id: str) -> list[dict[str, Any]]:
        """Return the headings of a document."""
        document = self.read(doc_id)
        headings: list[dict[str, Any]] = []
        for line in document.content.splitlines():
            match = HEADING_RE.match(line)
            if match:
                headings.append(
                    {"level": len(match.group(1)), "text": match.group(2).strip()}
                )
        return headings

    def cite(self, doc_id: str) -> dict[str, Any]:
        """Return a stable citation for a document."""
        document = self.read(doc_id)
        return {
            "doc_id": document.id,
            "title": document.title,
            "citation": (
                f"{document.title} — docs-mcp corpus ({document.path}), "
                f"sha256:{document.sha256[:12]}"
            ),
            "sha256": document.sha256,
        }
