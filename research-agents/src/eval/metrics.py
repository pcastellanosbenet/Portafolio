"""Deterministic metrics for the evaluation.

These metrics are deliberately transparent and reproducible. The LLM judge
adds a semantic task-success score, but it does not replace the structural
checks: citations must point to retrieved sources, expected facts are matched
against explicit surface forms, and abstention is detected with a fixed list of
phrases.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable

from src.citations import normalize_citations
from src.eval.models import EvalQuestion, EvaluationRecord

_SOURCE_ID_RE = re.compile(r"src_[0-9a-f]{12}")

_ABSTENTION_PHRASES = (
    "no hay evidencia suficiente",
    "no hay informacion suficiente",
    "no hay suficiente evidencia",
    "no se puede responder",
    "no puedo responder",
    "no es posible responder",
    "no se puede determinar",
    "no se pudo determinar",
    "no se encontro evidencia",
    "no se encontraron fuentes",
    "no se encontro ninguna fuente",
    "no se encontraron referencias",
    "no se pudo encontrar",
    "no se encontro informacion",
    "no se dispone de informacion",
    "no se dispone de evidencia",
    "no se dispone de datos",
    "no se cuenta con informacion",
    "no se cuenta con evidencia",
    "no hay informacion disponible",
    "no dispongo de informacion",
    "no existe informacion",
    "no contiene informacion",
    "no incluyen referencias",
    "sin informacion suficiente",
    "no esta en el corpus",
    "no se menciona en el corpus",
    "no se proporciona informacion",
    "no hay datos suficientes",
    "insufficient evidence",
    "not enough information",
    "cannot answer",
    "can't answer",
    "unable to answer",
    "no evidence was found",
    "no relevant sources",
)


def normalize_text(text: str) -> str:
    """Case-fold, remove accents and collapse whitespace for matching."""
    decomposed = unicodedata.normalize("NFD", text.casefold())
    without_accents = "".join(
        char for char in decomposed if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.split())


def _contains_any(normalized_text: str, variants: Iterable[str]) -> bool:
    return any(normalize_text(variant) in normalized_text for variant in variants)


def factual_coverage(
    answer: str,
    question: EvalQuestion,
) -> tuple[int, int, float, list[str]]:
    """Return covered facts, total facts, rate and missing fact ids."""
    total = len(question.expected_facts)
    if total == 0:
        return 0, 0, 0.0, []
    normalized = normalize_text(answer)
    covered: list[str] = []
    missing: list[str] = []
    for fact in question.expected_facts:
        if _contains_any(normalized, fact.any_of):
            covered.append(fact.id)
        else:
            missing.append(fact.id)
    return len(covered), total, len(covered) / total, missing


def cited_source_ids(record: EvaluationRecord) -> set[str]:
    """Collect source ids from Markdown citations and structured claims."""
    markdown = normalize_citations(record.answer_markdown)
    ids = set(_SOURCE_ID_RE.findall(markdown))
    for claim in record.claims:
        ids.update(claim.source_ids)
    return ids


def detect_abstention(answer: str, claims: list[object]) -> bool:
    """Detect an explicit refusal when the answer has no supported claims."""
    if claims:
        return False
    normalized = normalize_text(answer)
    if not normalized:
        return True
    return any(phrase in normalized for phrase in _ABSTENTION_PHRASES)


def compute_metrics(
    record: EvaluationRecord,
    question: EvalQuestion,
) -> dict[str, object]:
    """Compute all metrics that do not require human review."""
    covered, total, coverage, missing = factual_coverage(record.answer_markdown, question)
    expected_urls = set(question.expected_source_urls)
    known_sources = {source.source_id: source.url for source in record.sources}
    cited = cited_source_ids(record)

    valid_ids = {source_id for source_id in cited if source_id in known_sources}
    relevant_ids = {
        source_id
        for source_id in valid_ids
        if known_sources[source_id] in expected_urls
    }
    cited_count = len(cited)
    citation_precision = len(relevant_ids) / cited_count if cited_count else 0.0
    citation_validity = len(valid_ids) / cited_count if cited_count else 0.0
    recalled_urls = {known_sources[source_id] for source_id in relevant_ids}
    source_recall = (
        len(recalled_urls & expected_urls) / len(expected_urls) if expected_urls else 0.0
    )

    claims_total = len(record.claims)
    claims_valid = 0
    claims_relevant = 0
    for claim in record.claims:
        valid = [source_id for source_id in claim.source_ids if source_id in known_sources]
        if valid:
            claims_valid += 1
        if any(known_sources[source_id] in expected_urls for source_id in valid):
            claims_relevant += 1

    failed = record.status != "done"
    abstained = False if failed else detect_abstention(
        record.answer_markdown, list(record.claims)
    )
    judge = record.judge
    judge_coverage: float | None = None
    task_score: int | None = None
    if judge is not None:
        task_score = judge.score
        if question.expected_facts:
            judge_coverage = len(judge.covered_fact_ids) / len(question.expected_facts)

    metrics: dict[str, object] = {
        "task_success_score": task_score,
        "task_success_binary": None if task_score is None else float(task_score == 2),
        "facts_covered": covered,
        "facts_total": total,
        "factual_coverage": coverage,
        "judge_factual_coverage": judge_coverage,
        "missing_fact_ids": ", ".join(missing),
        "citation_count": cited_count,
        "citation_precision": citation_precision,
        "citation_validity": citation_validity,
        "source_recall": source_recall,
        "claims_total": claims_total,
        "claims_valid_support": claims_valid,
        "claims_relevant_support": claims_relevant,
        "claim_support_rate": (claims_valid / claims_total) if claims_total else None,
        "claim_relevance_rate": (claims_relevant / claims_total) if claims_total else None,
        "abstained": abstained,
        "abstention_correct": (
            None if question.answerable else float(abstained)
        ),
        "unsupported_claims_judged": (
            len(judge.unsupported_claims) if judge is not None else None
        ),
        "citation_issues_judged": (
            len(judge.citation_issues) if judge is not None else None
        ),
    }
    return metrics
