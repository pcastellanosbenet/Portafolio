"""Tests for judge parsing, validation and retry behavior."""

from __future__ import annotations

import pytest

from src.eval.judge import Judge, JudgeValidationError, normalize_judge_output
from src.eval.models import EvalQuestion, EvaluationRecord, ExpectedFact, JudgeOutput
from tests.fakes import FakeLLM


def make_question(*, answerable: bool = True) -> EvalQuestion:
    if not answerable:
        return EvalQuestion(
            id="U1",
            category="unanswerable",
            question="¿Cuál es la cuota actual de la API?",
            answerable=False,
        )
    return EvalQuestion(
        id="Q1",
        category="factual",
        question="¿Qué es el aprendizaje automático?",
        expected_facts=[
            ExpectedFact(id="f1", text="Definición.", any_of=["definicion"]),
            ExpectedFact(id="f2", text="Objetivo.", any_of=["objetivo"]),
        ],
        expected_source_urls=["https://es.wikipedia.org/wiki/A"],
    )


def make_record(question: EvalQuestion) -> EvaluationRecord:
    return EvaluationRecord(
        run_id="run",
        system="b0",
        question_id=question.id,
        category=question.category,
        question=question.question,
        answer_markdown="Una respuesta.",
        status="done",
    )


def test_normalize_fills_missing_ids_and_filters_unknown_ids() -> None:
    question = make_question()
    output = JudgeOutput(
        score=1,
        covered_fact_ids=["f1", "unknown"],
        missing_fact_ids=["unknown"],
        abstained=False,
        rationale="Parcial.",
    )

    normalized = normalize_judge_output(output, question)

    assert normalized.covered_fact_ids == ["f1"]
    assert normalized.missing_fact_ids == ["f2"]


def test_score_two_without_all_facts_is_invalid() -> None:
    question = make_question()
    output = JudgeOutput(
        score=2,
        covered_fact_ids=["f1"],
        missing_fact_ids=["f2"],
        abstained=False,
        rationale="Completa.",
    )

    with pytest.raises(JudgeValidationError, match="score 2"):
        normalize_judge_output(output, question)


def test_unanswerable_score_two_requires_abstention() -> None:
    question = make_question(answerable=False)
    output = JudgeOutput(
        score=2,
        abstained=False,
        rationale="Inventó una respuesta.",
    )

    with pytest.raises(JudgeValidationError, match="without abstention"):
        normalize_judge_output(output, question)


def test_judge_retries_an_inconsistent_output() -> None:
    question = make_question()
    record = make_record(question)
    invalid = JudgeOutput(
        score=2,
        covered_fact_ids=["f1"],
        missing_fact_ids=["f2"],
        abstained=False,
        rationale="Inconsistente.",
    )
    valid = JudgeOutput(
        score=2,
        covered_fact_ids=["f1", "f2"],
        missing_fact_ids=[],
        abstained=False,
        rationale="Completa.",
    )
    llm = FakeLLM({JudgeOutput: [invalid, valid]})

    result = Judge(llm).evaluate(question, record)

    assert result.output.score == 2
    assert result.output.covered_fact_ids == ["f1", "f2"]
    assert result.usage.total_tokens == 15
    assert len(llm.calls) == 2


def test_judge_raises_after_two_invalid_outputs() -> None:
    question = make_question()
    record = make_record(question)
    invalid = JudgeOutput(
        score=2,
        covered_fact_ids=["f1"],
        missing_fact_ids=["f2"],
        abstained=False,
        rationale="Inconsistente.",
    )
    llm = FakeLLM({JudgeOutput: invalid})

    with pytest.raises(JudgeValidationError, match="after two attempts"):
        Judge(llm).evaluate(question, record)
