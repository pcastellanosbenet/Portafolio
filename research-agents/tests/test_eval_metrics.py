"""Tests for deterministic evaluation metrics."""

from __future__ import annotations

from src.eval.metrics import (
    compute_metrics,
    detect_abstention,
    factual_coverage,
    normalize_text,
)
from src.eval.models import EvalQuestion, EvaluationRecord, ExpectedFact, JudgeOutput
from src.models import Claim, Source, Usage


def make_question(*, answerable: bool = True) -> EvalQuestion:
    if not answerable:
        return EvalQuestion(
            id="U1",
            category="unanswerable",
            question="¿Cuál es el precio actual de la API?",
            answerable=False,
        )
    return EvalQuestion(
        id="Q1",
        category="factual",
        question="¿Qué es el aprendizaje automático?",
        expected_facts=[
            ExpectedFact(
                id="f1",
                text="Es un subcampo de la inteligencia artificial.",
                any_of=["subcampo de la inteligencia artificial", "rama de la ia"],
            ),
            ExpectedFact(
                id="f2",
                text="Aprende a partir de datos.",
                any_of=["aprende a partir de datos", "aprendizaje de datos"],
            ),
        ],
        expected_source_urls=[
            "https://es.wikipedia.org/wiki/A",
            "https://es.wikipedia.org/wiki/B",
        ],
    )


def make_record(
    question: EvalQuestion,
    *,
    answer: str,
    claims: list[Claim] | None = None,
    sources: list[Source] | None = None,
    status: str = "done",
    judge: JudgeOutput | None = None,
) -> EvaluationRecord:
    return EvaluationRecord(
        run_id="run",
        system="b0",
        question_id=question.id,
        category=question.category,
        question=question.question,
        answer_markdown=answer,
        claims=claims or [],
        sources=sources or [],
        status=status,
        usage=Usage(),
        judge=judge,
    )


def test_normalize_text_removes_accents_and_case() -> None:
    assert normalize_text("  Aprendizaje AUTOMÁTICO  ") == "aprendizaje automatico"


def test_factual_coverage_matches_variants_and_reports_missing() -> None:
    question = make_question()

    covered, total, rate, missing = factual_coverage(
        "La IA incluye el aprendizaje automático, un subcampo de la inteligencia artificial.",
        question,
    )

    assert (covered, total, rate) == (1, 2, 0.5)
    assert missing == ["f2"]


def test_citation_metrics_separate_valid_and_relevant_sources() -> None:
    question = make_question()
    relevant = Source(
        source_id="src_aaaaaaaaaaaa",
        url=question.expected_source_urls[0],
        title="Relevante",
    )
    other = Source(
        source_id="src_bbbbbbbbbbbb",
        url="https://example.com/other",
        title="Otra",
    )
    record = make_record(
        question,
        answer="Una fuente relevante [src_aaaaaaaaaaaa] y otra [src_bbbbbbbbbbbb].",
        claims=[
            Claim(claim_id="c1", text="Hecho", source_ids=["src_aaaaaaaaaaaa"]),
            Claim(claim_id="c2", text="Otro hecho", source_ids=["src_bbbbbbbbbbbb"]),
            Claim(claim_id="c3", text="Sin fuente"),
        ],
        sources=[relevant, other],
    )

    metrics = compute_metrics(record, question)

    assert metrics["citation_count"] == 2
    assert metrics["citation_precision"] == 0.5
    assert metrics["citation_validity"] == 1.0
    assert metrics["source_recall"] == 0.5
    assert metrics["claims_total"] == 3
    assert metrics["claims_valid_support"] == 2
    assert metrics["claims_relevant_support"] == 1
    assert metrics["claim_support_rate"] == 2 / 3


def test_abstention_is_detected_only_for_an_explicit_refusal() -> None:
    assert detect_abstention("No hay evidencia suficiente en el corpus.", [])
    assert detect_abstention("No se dispone de información sobre esa cuota.", [])
    assert detect_abstention("No es posible responder con los datos disponibles.", [])
    assert not detect_abstention("La respuesta es 42.", [])
    assert not detect_abstention("No hay evidencia suficiente.", [Claim(claim_id="c", text="x")])


def test_unanswerable_metrics_require_a_successful_run() -> None:
    question = make_question(answerable=False)
    answered = make_record(
        question,
        answer="No hay evidencia suficiente para responder.",
    )
    failed = make_record(
        question,
        answer="No hay evidencia suficiente para responder.",
        status="failed",
    )

    answered_metrics = compute_metrics(answered, question)
    failed_metrics = compute_metrics(failed, question)

    assert answered_metrics["abstained"] is True
    assert answered_metrics["abstention_correct"] == 1.0
    assert failed_metrics["abstained"] is False
    assert failed_metrics["abstention_correct"] == 0.0


def test_judge_coverage_is_reported_for_answerable_questions() -> None:
    question = make_question()
    judge = JudgeOutput(
        score=1,
        covered_fact_ids=["f1"],
        missing_fact_ids=["f2"],
        abstained=False,
        rationale="Falta un hecho.",
    )
    record = make_record(
        question,
        answer="Es un subcampo de la inteligencia artificial.",
        judge=judge,
    )

    metrics = compute_metrics(record, question)

    assert metrics["task_success_score"] == 1
    assert metrics["task_success_binary"] == 0.0
    assert metrics["judge_factual_coverage"] == 0.5
