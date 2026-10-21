"""Answer synthesis with strict citations and an extractive fallback."""

from __future__ import annotations

import logging
import re

from src.citations import (
    build_citations,
    format_context,
    parse_answer,
    validate_citations,
)
from src.llm import LLMClient, LLMError
from src.models import AgentAnswer, RetrievedChunk
from src.text import truncate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a technical assistant for the KNX Standard v3.0.0.
Answer only from the provided sources. Never use outside knowledge.
Cite every factual claim with source markers such as [S1] or [S2].
If the sources do not contain enough evidence, abstain instead of guessing.
Answer in the same language as the user's question.
Return a JSON object with exactly these keys:
{"answer": "string", "citations": ["S1"], "abstained": false}
Do not add markdown fences or text outside the JSON object."""

STRICT_SUFFIX = """
The previous answer could not be validated. You must cite at least one source
from the context. If that is impossible, set abstained to true and explain why.
"""


def _user_prompt(question: str, context: str, *, strict: bool = False) -> str:
    prompt = (
        "Question:\n"
        f"{question}\n\n"
        "Sources:\n"
        f"{context}\n\n"
        "Remember: answer only from the sources and return valid JSON."
    )
    return prompt + (STRICT_SUFFIX if strict else "")


def _extractive_fallback(
    results: list[RetrievedChunk],
    reason: str,
) -> AgentAnswer:
    """Return a cited extract when no LLM is available or citations fail."""
    if not results:
        return AgentAnswer(
            answer="No encuentro evidencia suficiente en el estándar KNX v3.0.0.",
            citations=[],
            abstained=True,
            sources=[],
            trace=[{"step": "answer", "mode": "abstain", "reason": reason}],
            used_llm=False,
        )
    top = results[0]
    text = re.sub(r"\s+", " ", top.chunk.text).strip()
    sentences = re.split(r"(?<=[.!?])\s+", text)
    extract = " ".join(sentences[:2]).strip() or truncate(text, 500)
    answer = (
        "No he podido generar una respuesta verificada con el modelo local. "
        "Este es el fragmento más relevante recuperado:\n\n"
        f"{extract}"
    )
    return AgentAnswer(
        answer=answer,
        citations=build_citations({"S1": top}, [top.chunk.chunk_id]),
        abstained=False,
        sources=results,
        trace=[{"step": "answer", "mode": "extractive", "reason": reason}],
        used_llm=False,
    )


class AnswerService:
    def __init__(
        self,
        llm: LLMClient | None,
        *,
        max_context_tokens: int = 3000,
        max_chars_per_source: int = 1000,
    ) -> None:
        self.llm = llm
        self.max_context_tokens = max_context_tokens
        self.max_chars_per_source = max_chars_per_source

    def answer(self, question: str, results: list[RetrievedChunk]) -> AgentAnswer:
        if not results:
            return _extractive_fallback(results, "sin resultados")
        context, source_map = format_context(
            results,
            max_chars_per_source=self.max_chars_per_source,
        )
        if self.llm is None:
            return _extractive_fallback(results, "LLM no configurado")

        try:
            raw = self.llm.generate(SYSTEM_PROMPT, _user_prompt(question, context))
            payload = parse_answer(raw, source_map)
            valid, invalid = validate_citations(payload, source_map)
            if invalid and not payload.abstained:
                raw = self.llm.generate(
                    SYSTEM_PROMPT,
                    _user_prompt(question, context, strict=True),
                )
                payload = parse_answer(raw, source_map)
                valid, invalid = validate_citations(payload, source_map)
        except LLMError as error:
            logger.warning("Ollama no disponible: %s", error)
            return _extractive_fallback(results, str(error))

        if invalid:
            logger.warning("Citas inválidas: %s", invalid)
            return _extractive_fallback(results, "citas no verificables")

        if payload.abstained:
            return AgentAnswer(
                answer=payload.answer
                or "No encuentro evidencia suficiente en el estándar KNX v3.0.0.",
                citations=build_citations(source_map, valid),
                abstained=True,
                sources=results,
                trace=[{"step": "answer", "mode": "abstain", "reason": "modelo"}],
                used_llm=True,
            )

        return AgentAnswer(
            answer=payload.answer,
            citations=build_citations(source_map, valid),
            abstained=False,
            sources=results,
            trace=[{"step": "answer", "mode": "llm"}],
            used_llm=True,
        )


def make_extractive_service() -> AnswerService:
    return AnswerService(None)
