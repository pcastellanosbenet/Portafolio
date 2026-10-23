"""Loading and validation of the frozen corpus and evaluation questions."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.eval.models import QuestionSet
from src.tools.urls import canonicalize_url, source_id_for_url


class CorpusDocument(BaseModel):
    """One frozen source excerpt with attribution and an integrity hash."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: str = Field(min_length=1)
    kind: str = "web"
    language: str = ""
    license: str = Field(min_length=1)
    license_url: str = ""
    attribution: str = ""
    retrieved_at: date
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    aliases: list[str] = Field(default_factory=list)
    content: str = Field(min_length=1)

    @model_validator(mode="after")
    def _validate_integrity(self) -> CorpusDocument:
        if canonicalize_url(self.url) != self.url:
            raise ValueError(f"Document URL is not canonical: {self.url}")
        expected_source_id = source_id_for_url(self.url)
        if self.source_id != expected_source_id:
            raise ValueError(
                f"Document {self.doc_id} has source_id {self.source_id}, "
                f"expected {expected_source_id}."
            )
        actual_hash = hashlib.sha256(self.content.encode("utf-8")).hexdigest()
        if actual_hash != self.sha256:
            raise ValueError(
                f"Document {self.doc_id} failed its SHA-256 check: "
                f"stored {self.sha256}, actual {actual_hash}."
            )
        return self


class Corpus(BaseModel):
    """The versioned frozen corpus."""

    model_config = ConfigDict(extra="forbid")

    version: int = 1
    created_at: date
    description: str = ""
    license: str = "CC BY-SA 4.0"
    license_url: str = ""
    documents: list[CorpusDocument] = Field(min_length=1)
    queries: dict[str, list[dict[str, Any]]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_documents(self) -> Corpus:
        doc_ids = [document.doc_id for document in self.documents]
        source_ids = [document.source_id for document in self.documents]
        urls = [document.url for document in self.documents]
        if len(doc_ids) != len(set(doc_ids)):
            raise ValueError("Corpus document ids must be unique.")
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Corpus source ids must be unique.")
        if len(urls) != len(set(urls)):
            raise ValueError("Corpus URLs must be unique.")
        return self

    @property
    def urls(self) -> set[str]:
        return {document.url for document in self.documents}

    def by_url(self, url: str) -> CorpusDocument | None:
        canonical = canonicalize_url(url)
        for document in self.documents:
            if document.url == canonical:
                return document
        return None

    def by_source_id(self, source_id: str) -> CorpusDocument | None:
        for document in self.documents:
            if document.source_id == source_id:
                return document
        return None


def load_corpus(path: Path) -> Corpus:
    """Load and validate a corpus file."""
    if not path.is_file():
        raise FileNotFoundError(f"Corpus not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read corpus {path}: {exc}") from exc
    return Corpus.model_validate(raw)


def load_questions(path: Path) -> QuestionSet:
    """Load and validate a question set."""
    if not path.is_file():
        raise FileNotFoundError(f"Question set not found: {path}")
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"Could not read question set {path}: {exc}") from exc
    return QuestionSet.model_validate(raw)


def validate_questions_against_corpus(questions: QuestionSet, corpus: Corpus) -> None:
    """Check that every expected source URL exists in the frozen corpus."""
    known_urls = corpus.urls
    missing: list[str] = []
    for question in questions.questions:
        for url in question.expected_source_urls:
            canonical = canonicalize_url(url)
            if canonical not in known_urls:
                missing.append(f"{question.id}: {url}")
    if missing:
        raise ValueError(
            "Question set references URLs that are not in the corpus:\n"
            + "\n".join(sorted(missing))
        )
