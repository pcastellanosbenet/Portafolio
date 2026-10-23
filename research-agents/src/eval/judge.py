"""Independent LLM judge with a strict, validated output contract."""

from __future__ import annotations

from dataclasses import dataclass

from src.agents.base import StructuredLLM, json_payload
from src.budget import usage_from_metadata
from src.config import Settings
from src.eval.models import EvalQuestion, EvaluationRecord, JudgeOutput
from src.llm import LLMClient
from src.models import Usage
from src.prompts import messages


class JudgeValidationError(ValueError):
    """Raised when the judge output violates the rubric contract."""


def normalize_judge_output(output: JudgeOutput, question: EvalQuestion) -> JudgeOutput:
    """Validate and normalize fact identifiers and rubric consistency."""
    known = {fact.id for fact in question.expected_facts}
    covered = [fact_id for fact_id in output.covered_fact_ids if fact_id in known]
    missing = [
        fact_id
        for fact_id in output.missing_fact_ids
        if fact_id in known and fact_id not in covered
    ]
    # Remove duplicates while preserving order.
    covered = list(dict.fromkeys(covered))
    missing = list(dict.fromkeys(missing))

    if question.answerable:
        remaining = [fact_id for fact_id in known if fact_id not in covered]
        missing = list(dict.fromkeys([*missing, *remaining]))
        if output.score == 2 and missing:
            raise JudgeValidationError(
                "The judge gave score 2 but left expected facts uncovered: "
                + ", ".join(missing)
            )
    else:
        covered = []
        missing = []
        if output.score == 2 and not output.abstained:
            raise JudgeValidationError(
                "The judge gave score 2 to an unanswerable question without abstention."
            )
        if output.score == 0 and output.abstained:
            raise JudgeValidationError(
                "The judge gave score 0 although the answer abstained."
            )

    return output.model_copy(
        update={
            "covered_fact_ids": covered,
            "missing_fact_ids": missing,
            "unsupported_claims": list(dict.fromkeys(output.unsupported_claims)),
            "citation_issues": list(dict.fromkeys(output.citation_issues)),
        }
    )


def _judge_payload(question: EvalQuestion, record: EvaluationRecord) -> str:
    """Build a blind payload: the system name and usage are never included."""
    return json_payload(
        {
            "category": question.category,
            "question": question.question,
            "answerable": question.answerable,
            "reference_facts": [
                {"id": fact.id, "text": fact.text} for fact in question.expected_facts
            ],
            "expected_source_urls": question.expected_source_urls,
            "rubric_note": question.rubric,
            "candidate_answer": record.answer_markdown,
            "candidate_claims": [
                claim.model_dump(mode="json") for claim in record.claims
            ],
            "candidate_sources": [
                {
                    "source_id": source.source_id,
                    "title": source.title,
                    "url": source.url,
                }
                for source in record.sources
            ],
            "candidate_limitations": record.limitations,
        }
    )


@dataclass(frozen=True)
class JudgeResult:
    output: JudgeOutput
    usage: Usage


class Judge:
    """Score one answer with an LLM and validate the structured result."""

    def __init__(self, llm: StructuredLLM) -> None:
        self.llm = llm

    def evaluate(self, question: EvalQuestion, record: EvaluationRecord) -> JudgeResult:
        payload = _judge_payload(question, record)
        last_error: Exception | None = None
        for _attempt in range(2):
            correction = ""
            if last_error is not None:
                correction = (
                    "\n\nYour previous output violated the rubric: "
                    f"{last_error}. Return a corrected JSON object. "
                    "For an unanswerable question, score 2 requires abstained=true. "
                    "For an answerable question, score 2 requires every expected fact "
                    "to be listed in covered_fact_ids."
                )
            output, metadata = self.llm.invoke_structured(
                JudgeOutput,
                messages("judge", payload + correction),
            )
            try:
                normalized = normalize_judge_output(output, question)
            except JudgeValidationError as exc:
                last_error = exc
                continue
            return JudgeResult(
                output=normalized,
                usage=usage_from_metadata(metadata),
            )
        raise JudgeValidationError(
            f"The judge output remained invalid after two attempts: {last_error}"
        )


def build_judge(settings: Settings) -> Judge:
    """Build a judge client, preferably on a provider independent from the system."""
    provider, model = settings.judge_target
    if not settings.has_api_key_for(provider):
        raise ValueError(
            f"No API key is configured for the judge provider {provider!r}."
        )
    judge_settings = settings.model_copy(
        update={
            "llm_provider": provider,
            "llm_model": model,
            "llm_fast_model": model,
            "llm_fallback_provider": None,
            "llm_fallback_model": "",
            "llm_temperature": 0.0,
            "llm_tpm_limit": 0,
            "llm_max_retries": settings.judge_max_retries,
            "llm_max_output_tokens": settings.judge_max_output_tokens,
        }
    )
    return Judge(LLMClient(judge_settings))
