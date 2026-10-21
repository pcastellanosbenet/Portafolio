"""Prompt context formatting, answer parsing and citation validation."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from src.models import Citation, RetrievedChunk
from src.text import truncate

MARKER_RE = re.compile(r"\[(S\d+)\]")


@dataclass
class AnswerPayload:
    answer: str
    citations: list[str]
    abstained: bool


def format_context(
    results: list[RetrievedChunk],
    *,
    max_chars_per_source: int = 1000,
) -> tuple[str, dict[str, RetrievedChunk]]:
    """Create labelled context blocks and a marker-to-source map."""
    blocks: list[str] = []
    source_map: dict[str, RetrievedChunk] = {}
    for index, result in enumerate(results, start=1):
        marker = f"S{index}"
        source_map[marker] = result
        chunk = result.chunk
        blocks.append(
            "\n".join(
                [
                    f"[{marker}]",
                    f"Document: {chunk.title}",
                    f"Section: {chunk.section_path}",
                    f"Pages: {chunk.page_start}-{chunk.page_end}",
                    "Content:",
                    truncate(chunk.text, max_chars_per_source),
                ]
            )
        )
    return "\n\n".join(blocks), source_map


def _normalise_citation(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("chunk_id") or value.get("id") or value.get("source") or ""
    return str(value).strip()


def parse_answer(raw: str, source_map: dict[str, RetrievedChunk]) -> AnswerPayload:
    """Parse JSON if possible, with a permissive citation-marker fallback."""
    data: dict[str, object] | None = None
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            data = parsed
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(raw[start : end + 1])
                if isinstance(parsed, dict):
                    data = parsed
            except json.JSONDecodeError:
                data = None

    if data is not None:
        answer = str(data.get("answer", "")).strip()
        abstained = bool(data.get("abstained", False))
        raw_citations = data.get("citations", [])
        if isinstance(raw_citations, str):
            raw_citations = [raw_citations]
        citations: list[str] = []
        if isinstance(raw_citations, list):
            for item in raw_citations:
                value = _normalise_citation(item)
                if not value:
                    continue
                value = value.strip("[]")
                if value in source_map:
                    citations.append(source_map[value].chunk.chunk_id)
                else:
                    citations.append(value)
        if not citations:
            for marker in MARKER_RE.findall(answer):
                if marker in source_map:
                    citations.append(source_map[marker].chunk.chunk_id)
        if not answer:
            abstained = True
        return AnswerPayload(answer=answer, citations=citations, abstained=abstained)

    markers = MARKER_RE.findall(raw)
    cited_ids = [source_map[marker].chunk.chunk_id for marker in markers if marker in source_map]
    answer = MARKER_RE.sub("", raw).strip()
    return AnswerPayload(
        answer=answer,
        citations=cited_ids,
        abstained=not bool(answer),
    )


def validate_citations(
    payload: AnswerPayload,
    source_map: dict[str, RetrievedChunk],
) -> tuple[list[str], list[str]]:
    """Return valid and invalid citation chunk ids.

    An answer that is not an abstention must cite at least one retrieved source.
    """
    allowed = {result.chunk.chunk_id for result in source_map.values()}
    valid: list[str] = []
    invalid: list[str] = []
    for citation in payload.citations:
        if citation in allowed:
            if citation not in valid:
                valid.append(citation)
        else:
            invalid.append(citation)
    if not payload.abstained and not valid:
        invalid.append("missing-citation")
    return valid, invalid


def build_citations(
    source_map: dict[str, RetrievedChunk],
    chunk_ids: list[str],
    *,
    quote_chars: int = 240,
) -> list[Citation]:
    by_id = {result.chunk.chunk_id: result for result in source_map.values()}
    citations: list[Citation] = []
    seen: set[str] = set()
    for chunk_id in chunk_ids:
        result = by_id.get(chunk_id)
        if not result or chunk_id in seen:
            continue
        seen.add(chunk_id)
        chunk = result.chunk
        citations.append(
            Citation(
                chunk_id=chunk.chunk_id,
                doc_id=chunk.doc_id,
                title=chunk.title,
                section=chunk.section_path,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                quote=truncate(chunk.text.replace("\n", " "), quote_chars),
            )
        )
    return citations
