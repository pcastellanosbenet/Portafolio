"""Tests for the frozen corpus, question validation and retrieval."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.eval.corpus import (
    Corpus,
    load_corpus,
    load_questions,
    validate_questions_against_corpus,
)
from src.tools.base import FetchError, SearchError
from src.tools.frozen import FrozenPageFetcher, FrozenSearchBackend

REPO_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = REPO_ROOT / "eval" / "frozen" / "corpus.json"
QUESTIONS_PATH = REPO_ROOT / "eval" / "questions.json"


def test_real_corpus_and_questions_load() -> None:
    corpus = load_corpus(CORPUS_PATH)
    questions = load_questions(QUESTIONS_PATH)
    validate_questions_against_corpus(questions, corpus)

    assert len(corpus.documents) == 30
    assert len(questions.questions) == 20
    categories = {question.category for question in questions.questions}
    assert categories == {"factual", "comparison", "multi_hop", "unanswerable"}
    assert corpus.license == "CC BY-SA 4.0"
    assert all(len(document.sha256) == 64 for document in corpus.documents)


def test_corpus_rejects_a_document_with_a_bad_hash(tmp_path: Path) -> None:
    content = "Una fuente con contenido verificable."
    source_url = "https://es.wikipedia.org/wiki/Fuente_de_prueba"
    raw = {
        "version": 1,
        "created_at": "2026-10-23",
        "documents": [
            {
                "doc_id": "doc_test",
                "source_id": "src_" + hashlib.sha256(source_url.encode()).hexdigest()[:12],
                "title": "Fuente de prueba",
                "url": source_url,
                "kind": "wikipedia",
                "language": "es",
                "license": "CC BY-SA 4.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "attribution": "Wikipedia contributors",
                "retrieved_at": "2026-10-23",
                "sha256": "0" * 64,
                "aliases": ["prueba"],
                "content": content,
            }
        ],
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(raw), encoding="utf-8")

    with pytest.raises(ValueError, match="failed its SHA-256"):
        load_corpus(path)


def test_question_validation_rejects_a_url_outside_the_corpus() -> None:
    corpus = load_corpus(CORPUS_PATH)
    questions = load_questions(QUESTIONS_PATH)
    first = questions.questions[0]
    modified = first.model_copy(
        update={"expected_source_urls": [*first.expected_source_urls, "https://example.com/missing"]}
    )
    modified_set = questions.model_copy(update={"questions": [modified, *questions.questions[1:]]})

    with pytest.raises(ValueError, match="not in the corpus"):
        validate_questions_against_corpus(modified_set, corpus)


def test_frozen_search_returns_relevant_documents() -> None:
    backend = FrozenSearchBackend(CORPUS_PATH)
    cases = {
        "aprendizaje automático": "https://es.wikipedia.org/wiki/Aprendizaje_autom%C3%A1tico",
        "retropropagación": "https://es.wikipedia.org/wiki/Retropropagaci%C3%B3n",
        "transformer": "https://en.wikipedia.org/wiki/Transformer_(deep_learning)",
        "RAG": "https://es.wikipedia.org/wiki/Generaci%C3%B3n_aumentada_por_recuperaci%C3%B3n",
        "matriz de confusión": "https://es.wikipedia.org/wiki/Matriz_de_confusi%C3%B3n",
        "base de datos vectorial": "https://en.wikipedia.org/wiki/Vector_database",
    }
    for query, expected_url in cases.items():
        urls = {result.url for result in backend.search(query, max_results=5)}
        assert expected_url in urls, query


def test_frozen_fetch_returns_the_corpus_text() -> None:
    backend = FrozenSearchBackend(CORPUS_PATH)
    document = backend.documents[0]
    fetcher = FrozenPageFetcher(backend)

    page = fetcher.fetch(document["url"])

    assert page.url == document["url"]
    assert page.source_id == document["source_id"]
    assert page.text == document["content"]
    assert page.cached is True


def test_frozen_fetch_rejects_an_unknown_url() -> None:
    backend = FrozenSearchBackend(CORPUS_PATH)
    fetcher = FrozenPageFetcher(backend)

    with pytest.raises(FetchError, match="not in the frozen corpus"):
        fetcher.fetch("https://example.com/not-in-corpus")


def test_legacy_exact_query_format_is_still_supported(tmp_path: Path) -> None:
    data = {
        "queries": {
            "pregunta exacta": [
                {
                    "title": "Resultado legacy",
                    "url": "https://example.com/legacy",
                    "snippet": "Evidencia legacy",
                }
            ]
        }
    }
    path = tmp_path / "frozen.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    backend = FrozenSearchBackend(path)

    results = backend.search("pregunta exacta")

    assert results[0].title == "Resultado legacy"
    assert results[0].source_id.startswith("src_")


def test_missing_corpus_file_raises_search_error(tmp_path: Path) -> None:
    with pytest.raises(SearchError, match="Frozen corpus not found"):
        FrozenSearchBackend(tmp_path / "missing.json")


def test_corpus_document_model_rejects_duplicate_ids() -> None:
    raw = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    duplicate = dict(raw["documents"][0])
    raw["documents"] = [raw["documents"][0], duplicate]

    with pytest.raises(ValueError, match="document ids must be unique"):
        Corpus.model_validate(raw)
